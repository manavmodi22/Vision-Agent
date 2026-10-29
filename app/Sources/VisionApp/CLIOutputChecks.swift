import Foundation
import Darwin

enum CLIOutputChecks {
    /// A child process exercises immediate and exit-time framework-style stdout writes.
    static func runProbeIfRequested() {
        guard CommandLine.arguments.dropFirst().first == "--self-test-json-output" else { return }
        do {
            let response = try CLIJSONOutput()
            fputs("framework stdout before response\n", stdout)
            atexit { fputs("framework stdout at process exit\n", stdout) }
            if CommandLine.arguments.contains("--fail") { throw EngineError.protocolError("intentional child failure") }
            try response.emit(NativeReadings(texts: ["protocol"], barcodes: []))
            exit(0)
        } catch {
            FileHandle.standardError.write(Data((error.localizedDescription + "\n").utf8)); exit(7)
        }
    }
    static func run() throws -> Int {
        func child(fail: Bool) throws -> (Int32, Data, Data) {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: CommandLine.arguments[0]).standardizedFileURL
            process.arguments = ["--self-test-json-output"] + (fail ? ["--fail"] : [])
            let output = Pipe(), errors = Pipe()
            process.standardOutput = output; process.standardError = errors
            try process.run()
            // This controlled probe emits fewer than 200 diagnostic bytes, below pipe capacity.
            let data = output.fileHandleForReading.readDataToEndOfFile()
            let diagnostics = errors.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            return (process.terminationStatus, data, diagnostics)
        }
        let success = try child(fail: false)
        let decoded = try JSONDecoder().decode(NativeReadings.self, from: success.1)
        guard success.0 == 0, decoded.texts == ["protocol"], decoded.barcodes.isEmpty,
              success.1.filter({ $0 == 10 }).count == 1 else {
            throw EngineError.protocolError("CLI did not emit exactly one complete JSON response")
        }
        let diagnostics = String(decoding: success.2, as: UTF8.self)
        guard diagnostics.contains("framework stdout before response"), diagnostics.contains("framework stdout at process exit") else {
            throw EngineError.protocolError("Framework stdout escaped the diagnostic pipe")
        }
        let failure = try child(fail: true)
        guard failure.0 != 0, failure.1.isEmpty, String(decoding: failure.2, as: UTF8.self).contains("intentional child failure") else {
            throw EngineError.protocolError("CLI failure must use stderr and nonzero status without JSON output")
        }
        return 3
    }
}
