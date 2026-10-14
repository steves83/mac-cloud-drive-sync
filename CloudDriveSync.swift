// MIT License. Local launcher for the user's free rclone sync service.
// Keeps macOS privacy permission attached to this named application.
import Foundation
import Darwin

let base = FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent("Library/Application Support/CloudDriveSync")
let allowed = Set(["run", "initialize", "status", "enable", "disable", "verify-access"])
let action = CommandLine.arguments.dropFirst().first ?? "status"
guard allowed.contains(action) else { exit(2) }
let process = Process()
process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
process.arguments = action == "verify-access"
    ? [base.appendingPathComponent("verify-background-access.py").path]
    : [base.appendingPathComponent("sync.py").path, action]
process.currentDirectoryURL = base
do {
    try process.run()
    process.waitUntilExit()
    exit(process.terminationStatus)
} catch {
    fputs("Could not start Cloud Drive Sync: \(error)\n", stderr)
    exit(1)
}
