import Foundation
import Darwin

/// Owns the original stdout pipe; framework stdout remains redirected through exit.
final class CLIJSONOutput {
    private let output: FileHandle
    private var emitted = false
    init() throws {
        let descriptor = dup(STDOUT_FILENO)
        guard descriptor >= 0 else { throw EngineError.protocolError("Could not reserve the CLI response pipe") }
        guard fcntl(descriptor, F_SETFD, FD_CLOEXEC) == 0 else {
            close(descriptor)
            throw EngineError.protocolError("Could not protect the CLI response descriptor")
        }
        guard dup2(STDERR_FILENO, STDOUT_FILENO) >= 0 else {
            close(descriptor)
            throw EngineError.protocolError("Could not isolate CLI diagnostics")
        }
        // Any existing C stdio buffer now flushes to stderr, never into the JSON pipe.
        fflush(stdout)
        output = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
    }
    func emit<T: Encodable>(_ value: T) throws {
        guard !emitted else { throw EngineError.protocolError("A CLI response has already been emitted") }
        var data = try JSONEncoder().encode(value); data.append(10)
        emitted = true
        try output.write(contentsOf: data)
    }
}
