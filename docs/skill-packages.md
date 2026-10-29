# Versioned application playbooks

`agent/skills/packages/<id>/SKILL.md` contains TOML metadata between `+++`
delimiters followed by Markdown guidance and examples. These are application
resources, not user-uploaded instructions or dynamically downloaded plugins.
The registered packages cover authoring, detection, reading, segmentation,
tracking and alerting. Mentioning an unavailable adapter in guidance does not
make it executable.

Each package declares a semantic version, selection rule, task types, phases,
required inputs, suggested tools, output artifacts, validation recipe and failure
modes. The loader validates metadata, limits document/context size, selects by
the current task and phase, and computes SHA256 over the exact document bytes.
`SkillReference` records ID, version and hash in the plan and trace. Changes to
either metadata or body change the reference. Only registered bundled paths can
be loaded; project files and remote URLs cannot replace them.

Executable authority stays in the phase machine and executor. Suggested tools
can narrow the intersection of an existing phase grant and run grant; they can
never add deployment, delivery or another prohibited action. A playbook cannot
approve labels or grant capabilities. Semantic selection is bounded routing of
guidance, not a claim of general language understanding.

The distributable wheel includes all six Markdown documents. Runtime source
identity includes these resources so a playbook change cannot reuse an engine
with stale guidance. Native and Python hash algorithms must stay equivalent.
Tests cover identity changes, malformed metadata, contextual selection, quoted
data, context limits, untrusted paths and attempted authority expansion.
