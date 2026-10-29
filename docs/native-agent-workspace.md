# Describe-to-app workspace

The initial screen is a goal composer. A person can describe an outcome, attach their own media, or select verified public NVIDIA footage from the engine's sample catalog, then click **Build my app**. The app derives a project title from the goal, creates a custom project, imports selected samples, and starts the durable `POST /projects/{id}/build` operation. A project-name dialog is optional organization, not an onboarding prerequisite. No class ontology or detector picker blocks the agent.

Existing apps open in **Agent**. Conversation and real build progress occupy the left pane; the generated application and actual inference preview occupy the right. Preview is the default. Workflow details are inspectable on a secondary tab. The sidebar places annotations, workflow editing, zones, evaluation and evidence under Tools.

The UI polls `GET /projects/{id}/build` while Agent is visible. It renders only server-provided phase, status, questions, log entries, preview, candidate choice and evaluation. A failed or interrupted build stays visibly failed or interrupted; there are no simulated progress percentages or pre-completed steps. Build output is updated only when its server revision timestamp changes, preventing stale polling from replacing a manually requested preview.

Human checkpoints are contextual:

- `attach_media`: import representative examples, then continue the same goal.
- `answer_questions`: send the answer through `/build/continue`.
- `review_labels`: open the existing annotation editor; save and **Continue building** returns to Agent. This never changes reviewed flags automatically.
- `approve_training`: explicit confirmation before the improve request with `training_approved=true`.
- `approve_deployment`: the approval sheet opens directly in Agent with the selected candidate's measured results. Existing deployment API performs the approval; only then does native resume orchestration.

Candidate index also indexes the ordered evaluation array. Preview class counts are derived from actual detection labels; zone totals remain separately labelled. The app never interprets an all-zone total as a count for every class. Sample goals avoid claiming line-crossing or near-miss tracking.

Connection and engine identity validation remain in WorkspaceModel and EngineSupervisor. App creation, import, build, continuation and approval keep the existing connected-engine action gate. New UI does not start capture or request privacy permissions.

Native self-tests cover the ISO-timestamp build response, missing-media checkpoint, absent preview/approval state, and per-class count derivation. Full goal-to-preview inference and UI verification use the actual local engine and planner, separately from these contract tests.
