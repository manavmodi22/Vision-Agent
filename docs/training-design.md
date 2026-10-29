# Local custom-detector specialization

Owner: CV core. `train_detector(training, evaluation, project_root, model_id,
max_minutes=5, epochs=10, *, base_model_id=None) -> TrainingResult` is synchronous;
the service owns background execution, polling and bounded completion.

The default now specializes the **pretrained RT-DETRv2 R18** detector, using the
publisher checkpoint `PekingU/rtdetr_v2_r18vd`, pinned to revision
`5650961749fa93567c0d46fc7f43ea4f9e914107`. The [publisher model card](https://huggingface.co/PekingU/rtdetr_v2_r18vd)
and [official code repository](https://github.com/lyuwenyu/RT-DETR) identify
Apache-2.0 licensing. The official checkpoint is COCO-trained; it does not contain
warehouse-specific pallet, damage or forklift classes by default.

New class heads retain learned rows for matching class names, initialize unseen
class probabilities to a 0.01 prior, and retain pretrained backbone/localization
weights. Existing RT-DETRv2 checkpoints can resume with the same or an expanded
class roster; learned matching rows are preserved. Model manifests record the
upstream model/revision, immediate base weight hash, class mapping, retained
classes, random seed, train/holdout hashes, device, steps and loss. Model, config
and processor are saved locally with safe serialization; no pickle is loaded.

MPS forward, loss, backward, optimizer update, save/reload and held-out inference
have been exercised on this Apple M4 Pro. Pure PyTorch kernels are selected rather
than CUDA extensions. CPU is selected explicitly when MPS is unavailable; a device
failure does not silently substitute another detector. No downloads occur inside
a training job. Install the pinned checkpoint with `scripts/install_rtdetr.py`.

Existing SSDLite checkpoints remain loadable and resumable. Scratch SSDLite is
retained only for its original verification tests; it is no longer the default
custom-model workflow. Its former pretrained-license uncertainty is not applied
to the RT-DETRv2 publisher checkpoint, whose model card supplies an explicit license.

Before training: every selected label must be reviewed, the training set must
contain positive objects, evaluation must be separate, image contents cannot
repeat across splits (even under renamed files), and rectangle demo fixtures are
rejected. A holdout with adjacent frames from one camera is not an independent
scene benchmark. The budget is checked between optimizer steps; an in-progress
native operation can exceed it. Scoring, model selection and user deployment
approval are separate. A training job completing does not imply a useful model.
