import Foundation
import Darwin

enum EngineError: LocalizedError {
    case transport(String), protocolError(String), server(Int, String)
    var errorDescription: String? {
        switch self {
        case .transport(let s), .protocolError(let s): return s
        case .server(_, let s): return s
        }
    }
}

struct HTTPResponse {
    let status: Int
    let body: Data
    static func parse(_ raw: Data) throws -> HTTPResponse {
        let separator = Data("\r\n\r\n".utf8)
        guard let split = raw.range(of: separator),
              let header = String(data: raw[..<split.lowerBound], encoding: .utf8),
              let status = Int(header.components(separatedBy: "\r\n")[0].split(separator: " ").dropFirst().first ?? "")
        else { throw EngineError.protocolError("The engine returned an invalid HTTP response.") }
        let body = Data(raw[split.upperBound...])
        let lines = header.components(separatedBy: "\r\n").dropFirst()
        var headers: [String: String] = [:]
        for line in lines {
            let parts = line.split(separator: ":", maxSplits: 1)
            if parts.count == 2 { headers[parts[0].lowercased()] = parts[1].trimmingCharacters(in: .whitespaces) }
        }
        if headers["transfer-encoding"]?.lowercased().contains("chunked") == true {
            return HTTPResponse(status: status, body: try decodeChunks(body))
        }
        if let declared = headers["content-length"], let length = Int(declared), length != body.count {
            throw EngineError.protocolError("The engine response was incomplete.")
        }
        return HTTPResponse(status: status, body: body)
    }
    static func decodeChunks(_ data: Data) throws -> Data {
        var offset = 0
        var output = Data()
        let separator = Data("\r\n".utf8)
        while offset < data.count {
            guard let range = data.range(of: separator, in: offset..<data.count),
                  let line = String(data: data[offset..<range.lowerBound], encoding: .utf8),
                  let size = Int(line.split(separator: ";")[0], radix: 16) else {
                throw EngineError.protocolError("Invalid chunked engine response.")
            }
            offset = range.upperBound
            if size == 0 { return output }
            guard size >= 0, size <= data.count - offset - 2 else {
                throw EngineError.protocolError("Truncated chunked engine response.")
            }
            output.append(data[offset..<offset+size])
            offset += size + 2
        }
        throw EngineError.protocolError("Missing response terminator.")
    }
}

struct EngineClient {
    let socketPath: String
    func request<T: Decodable>(_ method: String = "GET", _ path: String,
                               body: [String: JSONValue]? = nil, as: T.Type = T.self) async throws -> T {
        let data = try body.map { try JSONEncoder().encode($0) }
        let result = try await rawRequest(method, path, body: data)
        do { return try JSONDecoder().decode(T.self, from: result) }
        catch { throw EngineError.protocolError("Could not read engine response: \(error.localizedDescription)") }
    }
    func send<T: Encodable, R: Decodable>(_ method: String, _ path: String, value: T, as: R.Type) async throws -> R {
        let result = try await rawRequest(method, path, body: JSONEncoder().encode(value))
        return try JSONDecoder().decode(R.self, from: result)
    }
    func rawRequest(_ method: String, _ path: String, body: Data? = nil) async throws -> Data {
        let socket = socketPath
        return try await Task.detached(priority: .userInitiated) {
            try Self.perform(socketPath: socket, method: method, path: path, body: body)
        }.value
    }
    private static func perform(socketPath: String, method: String, path: String, body: Data?) throws -> Data {
        let fd = Darwin.socket(AF_UNIX, SOCK_STREAM, 0)
        guard fd >= 0 else { throw EngineError.transport("Unable to create local engine socket.") }
        defer { Darwin.close(fd) }
        var noSignal: Int32 = 1
        setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &noSignal, socklen_t(MemoryLayout<Int32>.size))
        // Leave headroom beyond the server's bounded 185-second planner request.
        var timeout = timeval(tv_sec: 240, tv_usec: 0)
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))
        setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))
        var address = sockaddr_un()
        address.sun_family = sa_family_t(AF_UNIX)
        let bytes = Array(socketPath.utf8CString)
        guard bytes.count <= MemoryLayout.size(ofValue: address.sun_path) else {
            throw EngineError.transport("The engine socket path is too long.")
        }
        withUnsafeMutableBytes(of: &address.sun_path) { pointer in
            for (index, byte) in bytes.enumerated() { pointer[index] = UInt8(bitPattern: byte) }
        }
        address.sun_len = UInt8(MemoryLayout<sockaddr_un>.size)
        let connected = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.connect(fd, $0, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }
        guard connected == 0 else { throw EngineError.transport("Engine unavailable. \(String(cString: strerror(errno)))") }
        let payload = body ?? Data()
        let header = "\(method) \(path) HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\nContent-Type: application/json\r\nContent-Length: \(payload.count)\r\n\r\n"
        var request = Data(header.utf8)
        request.append(payload)
        try request.withUnsafeBytes { buffer in
            var offset = 0
            while offset < request.count {
                let sent = Darwin.send(fd, buffer.baseAddress!.advanced(by: offset), request.count - offset, 0)
                guard sent > 0 else { throw EngineError.transport("Could not send the engine request.") }
                offset += sent
            }
        }
        var received = Data()
        var buffer = [UInt8](repeating: 0, count: 65536)
        while true {
            let length = Darwin.recv(fd, &buffer, buffer.count, 0)
            if length == 0 { break }
            guard length > 0 else { throw EngineError.transport("The engine timed out or disconnected. Check engine logs.") }
            received.append(contentsOf: buffer.prefix(length))
            guard received.count < 64 * 1024 * 1024 else { throw EngineError.protocolError("Engine response exceeds 64 MB.") }
        }
        let response = try HTTPResponse.parse(received)
        guard (200..<300).contains(response.status) else {
            let object = try? JSONDecoder().decode([String: JSONValue].self, from: response.body)
            let message = object?["detail"]?.string ?? String(data: response.body, encoding: .utf8) ?? "Engine request failed."
            throw EngineError.server(response.status, message)
        }
        return response.body
    }
}
