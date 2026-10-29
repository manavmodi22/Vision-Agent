import SwiftUI

// Explicit alias selects the backwards-compatible property wrapper when the
// command-line SDK lacks the macOS 27 SwiftUIMacros compiler plugin.
typealias NativeState<Value> = SwiftUI.State<Value>

enum Studio {
    static let background = Color(red: 0.055, green: 0.068, blue: 0.084)
    static let panel = Color(red: 0.088, green: 0.105, blue: 0.125)
    static let raised = Color(red: 0.12, green: 0.14, blue: 0.16)
    static let accent = Color(red: 0.44, green: 0.88, blue: 0.72)
    static let muted = Color(red: 0.55, green: 0.61, blue: 0.66)
}
extension View {
    func panel() -> some View {
        self.padding(20).background(Studio.panel).clipShape(RoundedRectangle(cornerRadius: 14))
            .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(.white.opacity(0.06)))
    }
}
struct Eyebrow: View {
    let text: String
    var body: some View { Text(text.uppercased()).font(.system(size: 10, weight: .semibold, design: .monospaced)).tracking(1.5).foregroundStyle(Studio.muted) }
}
struct StatusPill: View {
    let text: String
    var color: Color = Studio.accent
    var body: some View {
        HStack(spacing: 5) { Circle().fill(color).frame(width: 5, height: 5); Text(text).font(.system(size: 11, weight: .medium)) }
            .foregroundStyle(color).padding(.horizontal, 9).padding(.vertical, 5).background(color.opacity(0.1)).clipShape(Capsule())
    }
}
struct MetricCard: View {
    let title: String
    let value: String
    let caption: String
    var body: some View {
        VStack(alignment: .leading, spacing: 9) { Eyebrow(text: title); Text(value).font(.system(size: 30, weight: .medium, design: .rounded)); Text(caption).font(.caption).foregroundStyle(Studio.muted) }
            .frame(maxWidth: .infinity, alignment: .leading).panel()
    }
}
struct EmptyCard: View {
    let symbol: String
    let title: String
    let detail: String
    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: symbol).font(.system(size: 32, weight: .light)).foregroundStyle(Studio.accent)
            Text(title).font(.title3.weight(.medium))
            Text(detail).font(.callout).foregroundStyle(Studio.muted).multilineTextAlignment(.center).frame(maxWidth: 420)
        }.frame(maxWidth: .infinity, maxHeight: .infinity).padding(40)
    }
}
