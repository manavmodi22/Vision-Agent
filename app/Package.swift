// swift-tools-version: 6.0
import PackageDescription
let package = Package(
    name: "VisionApp",
    platforms: [.macOS(.v15)],
    products: [.executable(name: "VisionApp", targets: ["VisionApp"])],
    targets: [
        .executableTarget(name: "VisionApp", swiftSettings: [.swiftLanguageMode(.v5)]),
        .testTarget(name: "VisionAppTests", dependencies: ["VisionApp"])
    ]
)
