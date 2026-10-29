# Captured-call transport comparison

Three local attempts at the same captured call 2 distinguish transport behavior from task quality:

| Transport | Result | Generated tokens |
| --- | --- | ---: |
| Original schema-constrained final JSON | Repeated analysis, length stop, empty final | 1,400 |
| Omit only response_format | Stop, empty final, no parsed function/tool call | 66 |
| Declare and force one submit_decision function with the same schema | One complete function call; arguments pass shape/revision/reference checks | 104 |

The no-grammar request retained every other original wire field. Regenerated current contracts had an empty diff; its actual rendered prompt hash stayed `55a959283974624fde86ae7434c43cef5c21e098ec53f75edd0fb52ff6e7b74d`. The native-function variant retained those same model/messages/temperature 0/max_tokens 1400 fields, registered the exact grounded NextAction schema as function parameters, forced that function, and disabled parallel calls. Its template necessarily included the function declaration: 3,893 prompt tokens versus 3,784, with a different rendered hash. It is a transport intervention, not an identical rendered prompt comparison.

The valid candidate requests inspection of `model.apple-vision`. Its cited-observation list is empty. It demonstrates a bounded valid submission, without establishing that prior evidence was causally used, that the action is executable/authorized, or that any image was processed. No candidate was dispatched; `authority_validated` remains false. No A0 or model-promotion claim follows.

The production choice remains explicit: independent decision RPCs submit a typed envelope for the host to validate and execute; structured-final output remains the default. This result does not require a broad framework rewrite or claim that the actual vision capabilities were directly called as native functions.

Sources: `artifacts/a0-investigation/gpt-oss-qualification/first-live-failure/task.json`, `call2-no-grammar/`, and `call2-native-function/`. This comparison was checked against their saved requests, receipts, responses and candidate, with no inference or backend edits.
