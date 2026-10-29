# Dependency decisions

Only libraries are bundled. LM Studio is an optional user-installed model server;
no Roboflow packages or services are used.

| Dependency | Purpose | Declared upstream license |
|---|---|---|
| Python 3.12 | Engine runtime | PSF |
| Pydantic 2 | Validate every public contract | MIT |
| FastAPI / Starlette / Uvicorn | Local HTTP over Unix socket | MIT / BSD |
| httpx | Local model requests, socket integration tests | BSD-3-Clause |
| MCP Python SDK 1.x | Standard stdio protocol for agent tools | MIT |
| Pydantic AI slim 1.x | Typed planner output and bounded retries | MIT |
| Pillow / NumPy | Image loading, crops and numeric operations | HPND / BSD |
| OpenCV headless | Recorded video sampling | Apache-2.0 |
| filelock | Cross-process project and training locks | Unlicense |
| SciPy / torchvision / safetensors (optional) | Processing, training and safe weights | BSD / BSD / Apache-2.0 |
| PyTorch / Transformers (optional) | Real local OWLv2 inference | BSD-3-Clause / Apache-2.0 |
| pytest / Ruff / mypy (development) | Behavioral tests, lint and strict types | MIT |

Actively maintained upstream projects were selected; versions are captured in the
generated lock file. We retain MCP 1.x and Pydantic AI 1.x for an explicitly tested
API surface rather than assuming compatibility across major versions.

Model code and weights are separate license decisions. The model registry must
show both identity and license. The synthetic fixture detector has no learned
weights and proves plumbing only. OWLv2's official Google model card declares
Apache-2.0; the configured local snapshot must be supplied separately.

References checked 2026-10-28:
* https://py.sdk.modelcontextprotocol.io/get-started/installation/
* https://github.com/pydantic/pydantic-ai/blob/main/docs/models/compatible-apis.md
* https://huggingface.co/google/owlv2-base-patch16-ensemble

Redistribution/signing/notarization and product-specific legal review remain
release tasks. No license is assigned to the user's repository by this build.
