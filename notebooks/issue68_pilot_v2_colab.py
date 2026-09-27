# Paste each marked section into a separate Colab cell.
# Required first:
#   MyDrive/DETECTER-training/train_verified.jsonl
#   MyDrive/DETECTER-training/source_audit.json
#   MyDrive/DETECTER-training/images/<manifest path>
# train_verified.jsonl: one original image per source_group. Fields:
# image_id,path,sha256,source_group,upstream_source,upstream_record_id,
# subset (sofake/ntire2026/hard_real),category,label
# (real/full_synthetic),generator,image_kind,split (train/validation).
# source_audit.json: {"sources": {"upstream_source": {
#   "decision": "include" or "exclude", "license": "...",
#   "evidence": "...", "reason": "..."}}}
# So-Fake rows require the actual upstream source and record, not "So-Fake-Set".
# Evaluation additionally needs condition=clean/resize1024_jpeg75/sns_multihop,
# audited image_kind, capture_session_id for real, prompt_group_id for
# generated images, origin_sha256 for all variants, and platform_receipt
# for real SNS replay.

# %% SETUP (run again before EVALUATE if the Colab runtime was restarted)
import importlib.util
import subprocess
import sys

packages = {
    "timm": "timm",
    "pillow_heif": "pillow-heif",
    "scipy": "scipy",
    "pandas": "pandas",
}
missing_packages = [
    package
    for module, package in packages.items()
    if importlib.util.find_spec(module) is None
]
if missing_packages:
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-q", *missing_packages]
    )

# %% TRAIN
from google.colab import drive

drive.mount("/content/drive")

import copy
import hashlib
import io
import json
import random
from collections import Counter
from pathlib import Path

import timm
import torch
import torch.nn.functional as F
from PIL import Image, ImageEnhance, ImageOps
from torch import nn
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms
from tqdm.auto import tqdm

BASE = Path("/content/drive/MyDrive/DETECTER-training")
MANIFEST = BASE / "train_verified.jsonl"
SOURCE_AUDIT = BASE / "source_audit.json"
IMAGE_ROOT = BASE / "images"
MODEL_ID = "vit_base_patch14_dinov2.lvd142m"
PROTOCOL = "issue68-paired-v2"
SEED, EPOCHS, BATCH, LR = 20260927, 3, 32, 1e-3
KL_WEIGHT, CONTRAST_WEIGHT = 1.0, 0.1

if not MANIFEST.is_file() or not SOURCE_AUDIT.is_file():
    raise FileNotFoundError(
        "監査済みの train_verified.jsonl と source_audit.json が必要です。"
        "現行 train_clean.jsonl は上流出所が不明なので使用できません。"
    )
rows = [json.loads(line) for line in MANIFEST.read_text().splitlines() if line.strip()]
sources = json.loads(SOURCE_AUDIT.read_text())["sources"]
required = {
    "image_id",
    "path",
    "sha256",
    "source_group",
    "upstream_source",
    "upstream_record_id",
    "subset",
    "category",
    "label",
    "generator",
    "image_kind",
    "split",
}
if any(required - row.keys() for row in rows):
    raise ValueError("学習台帳に必須列が不足しています")
if len({row["image_id"] for row in rows}) != len(rows):
    raise ValueError("画像IDが重複しています")

train_rows, validation_rows = [], []
excluded = Counter()
for row in rows:
    source = row["upstream_source"]
    audit_entry = sources.get(source)
    normalized_source = (
        str(source or "").lower().replace("_", "").replace("-", "").replace(" ", "")
    )
    if (
        not source
        or normalized_source in {"unknown", "sofakeset"}
        or not row["upstream_record_id"]
        or not audit_entry
    ):
        raise ValueError(f"{row['image_id']}: 元画像ごとの上流出所・レコードが必要です")
    if audit_entry["decision"] == "exclude":
        if not audit_entry.get("reason"):
            raise ValueError(f"{source}: 除外理由がありません")
        excluded[source] += 1
        continue
    if (
        audit_entry["decision"] != "include"
        or not audit_entry.get("license")
        or not audit_entry.get("evidence")
    ):
        raise ValueError(f"{source}: 利用条件と確認根拠を承認してください")
    if any(
        name in normalized_source
        for name in ("celeba", "ffhq", "openforensics", "wider", "sofakeood")
    ):
        raise ValueError(f"{row['image_id']}: 除外対象の上流出所が承認されています")
    if not row["category"]:
        raise ValueError(f"{row['image_id']}: 層化用カテゴリが不明です")
    if row["label"] not in {"real", "full_synthetic"}:
        raise ValueError(f"{row['image_id']}: TAMPERED/その他のラベルは対象外です")
    if row["split"] not in {"train", "validation"}:
        raise ValueError(f"{row['image_id']}: 学習/検証以外の分割が混入しています")
    if row["subset"] not in {"sofake", "ntire2026", "hard_real"}:
        raise ValueError(f"{row['image_id']}: データ区分が不明です")
    if row["subset"] == "ntire2026" and row.get("upstream_split") != "train":
        raise ValueError(
            f"{row['image_id']}: NTIRE 2026 のtrain分割だけを学習に使います"
        )
    if row["subset"] == "hard_real" and row["label"] != "real":
        raise ValueError(f"{row['image_id']}: 自前hard-realは実写のみです")
    generator = str(row["generator"] or "").lower()
    normalized_generator = "".join(char for char in generator if char.isalnum())
    if row["label"] == "full_synthetic" and not generator:
        raise ValueError(f"{row['image_id']}: 生成器名が必要です")
    if "gptimage2" in normalized_generator or "nanobanana" in normalized_generator:
        raise ValueError(f"{row['image_id']}: 評価専用の生成器が学習側にあります")
    if row["split"] == "train":
        train_rows.append(row)
    else:
        validation_rows.append(row)

if not 30000 <= len(train_rows) <= 100000 or not validation_rows:
    raise ValueError(
        f"学習30,000〜100,000行と別の検証群が必要: {len(train_rows)}, {len(validation_rows)}"
    )
if {row["subset"] for row in train_rows} != {"sofake", "ntire2026", "hard_real"}:
    raise ValueError("So-Fake、NTIRE 2026 train、自前hard-realが必要です")
subset_counts = Counter(row["subset"] for row in train_rows)
if min(subset_counts.values()) < 1000:
    raise ValueError(f"各データ区分に少なくとも1,000行が必要です: {subset_counts}")
if not any(
    row["subset"] == "hard_real" and row["image_kind"] == "unknown"
    for row in train_rows
):
    raise ValueError("kind=unknownの自前hard-realが必要です")
class_counts = Counter(row["label"] for row in train_rows)
if len(class_counts) != 2 or min(class_counts.values()) < len(train_rows) // 4:
    raise ValueError(f"実写と完全生成の学習行数が極端に偏っています: {class_counts}")
included = train_rows + validation_rows
if len({row["source_group"] for row in included}) != len(included):
    raise ValueError("元画像群を重複させず、train/validationを分けてください")
if len(
    {(row["upstream_source"], row["upstream_record_id"]) for row in included}
) != len(included):
    raise ValueError("同じ上流原画像が複数行または分割間にあります")
if len({row["sha256"] for row in included}) != len(included):
    raise ValueError("同じ画像バイトが複数行にあります")

root = IMAGE_ROOT.resolve()


def image_path(row):
    path = (IMAGE_ROOT / row["path"]).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"{row['image_id']}: 学習画像の保存先が不正です")
    return path


for row in tqdm(included, desc="画像ハッシュを確認"):
    path = image_path(row)
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("rb") as image_file:
        actual = hashlib.file_digest(image_file, "sha256").hexdigest()
    if actual != row["sha256"]:
        raise ValueError(f"{row['image_id']}: 画像のSHA-256が一致しません")

report = {
    "manifest_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
    "source_audit_sha256": hashlib.sha256(SOURCE_AUDIT.read_bytes()).hexdigest(),
    "train_rows": len(train_rows),
    "validation_rows": len(validation_rows),
    "by_subset": dict(Counter(row["subset"] for row in train_rows)),
    "by_source": dict(Counter(row["upstream_source"] for row in train_rows)),
    "by_category": dict(Counter(row["category"] for row in train_rows)),
    "by_generator": dict(
        Counter(
            row["generator"] for row in train_rows if row["label"] == "full_synthetic"
        )
    ),
    "by_class": dict(class_counts),
    "excluded_by_source": dict(excluded),
    "excluded_reasons": {source: sources[source]["reason"] for source in excluded},
}
(BASE / "pilot_v2_data_report.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2)
)
print("学習データ:", report["by_subset"], "除外:", report["excluded_by_source"])

try:
    from pillow_heif import register_heif_opener
except ImportError as exc:
    raise RuntimeError(
        "先にColabで %pip install pillow-heif を実行してください"
    ) from exc
register_heif_opener()


def degraded_view(image, rng):
    image = image.copy()
    if rng.random() < 0.9:
        side = rng.choice((768, 896, 1024, 1152, 1280))
        image.thumbnail((side, side), Image.Resampling.LANCZOS)
    if rng.random() < 0.15:
        canvas = Image.new(
            "RGB", (1080, 1920), rng.choice(((255, 255, 255), (24, 24, 24)))
        )
        image.thumbnail((1040, 1880), Image.Resampling.LANCZOS)
        canvas.paste(image, ((1080 - image.width) // 2, (1920 - image.height) // 2))
        image = canvas
    if rng.random() < 0.4:
        image = ImageEnhance.Color(image).enhance(rng.uniform(0.7, 1.3))
        image = ImageEnhance.Contrast(image).enhance(rng.uniform(0.8, 1.2))
    buf = io.BytesIO()
    if rng.random() < 0.3:
        image.save(buf, "WEBP", quality=rng.randint(60, 90))
    else:
        image.save(buf, "JPEG", quality=max(40, min(95, round(rng.gauss(75, 10)))))
    buf.seek(0)
    image = Image.open(buf).convert("RGB")
    if rng.random() < 0.15:
        buf = io.BytesIO()
        image.save(buf, "JPEG", quality=rng.randint(65, 90))
        buf.seek(0)
        image = Image.open(buf).convert("RGB")
    return image


preprocess = transforms.Compose(
    [
        transforms.Resize(518),
        transforms.CenterCrop(518),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ]
)


class PairedImages(Dataset):
    def __init__(self, records):
        self.records, self.epoch = records, 0

    def __len__(self):
        return len(self.records)

    def __getitem__(self, index):
        row = self.records[index]
        with Image.open(image_path(row)) as source:
            clean = ImageOps.exif_transpose(source).convert("RGB")
        digest = hashlib.blake2b(
            f"{SEED}|{self.epoch}|{row['image_id']}".encode(), digest_size=8
        ).digest()
        degraded = degraded_view(clean, random.Random(int.from_bytes(digest, "big")))
        return (
            preprocess(clean),
            preprocess(degraded),
            int(row["label"] == "full_synthetic"),
        )


class PilotHead(nn.Module):
    def __init__(self, width):
        super().__init__()
        self.norm = nn.LayerNorm(width)
        self.shared = nn.Linear(width, 256)
        self.classifier = nn.Linear(256, 2)

    def forward(self, features):
        hidden = F.gelu(self.shared(self.norm(features)))
        return hidden, self.classifier(hidden)


def symmetric_kl(clean_logits, degraded_logits):
    clean = F.log_softmax(clean_logits, dim=1)
    degraded = F.log_softmax(degraded_logits, dim=1)
    return (
        F.kl_div(clean, degraded.exp(), reduction="batchmean")
        + F.kl_div(degraded, clean.exp(), reduction="batchmean")
    ) / 2


def paired_contrastive(clean_hidden, degraded_hidden, labels):
    similarity = (
        F.normalize(clean_hidden, dim=1) @ F.normalize(degraded_hidden, dim=1).T / 0.07
    )
    identity = torch.eye(len(labels), dtype=torch.bool, device=labels.device)
    similarity = similarity.masked_fill(
        labels[:, None].eq(labels[None, :]) & ~identity, -1e4
    )
    targets = torch.arange(len(labels), device=labels.device)
    return (
        F.cross_entropy(similarity, targets) + F.cross_entropy(similarity.T, targets)
    ) / 2


if not torch.cuda.is_available():
    raise RuntimeError("ColabのGPUランタイムを選択してください")
device = torch.device("cuda")
backbone = timm.create_model(MODEL_ID, pretrained=True, num_classes=0).to(device).eval()
backbone.requires_grad_(False)
backbone_hash = hashlib.sha256()
for name, value in sorted(backbone.state_dict().items()):
    backbone_hash.update(name.encode())
    backbone_hash.update(value.detach().cpu().contiguous().numpy().tobytes())
backbone_sha256 = backbone_hash.hexdigest()

# Cの損失が分類器と共有する層へ勾配を持つことを確認する。
probe = PilotHead(backbone.num_features).to(device)
dummy = torch.randn(4, backbone.num_features, device=device)
hidden0, _ = probe(dummy)
hidden1, _ = probe(dummy + 0.01)
paired_contrastive(
    hidden0, hidden1, torch.tensor([0, 0, 1, 1], device=device)
).backward()
assert probe.shared.weight.grad is not None and probe.shared.weight.grad.abs().sum() > 0
del probe, dummy, hidden0, hidden1

torch.manual_seed(SEED)
initial_head = PilotHead(backbone.num_features).to(device)
heads = {arm: copy.deepcopy(initial_head) for arm in "ABC"}
optimizers = {
    arm: torch.optim.AdamW(head.parameters(), lr=LR) for arm, head in heads.items()
}
history = {arm: [] for arm in "ABC"}
dataset = PairedImages(train_rows)
generator = torch.Generator().manual_seed(SEED)
loader = DataLoader(
    dataset,
    batch_size=BATCH,
    shuffle=True,
    generator=generator,
    num_workers=2,
    pin_memory=True,
    drop_last=True,
)
validation = PairedImages(validation_rows)
validation.epoch = -1
validation_loader = DataLoader(
    validation, batch_size=BATCH, num_workers=2, pin_memory=True
)

for epoch in range(EPOCHS):
    dataset.epoch = epoch
    for head in heads.values():
        head.train()
    totals = {arm: {"loss": 0.0, "clean": 0, "degraded": 0, "n": 0} for arm in "ABC"}
    for clean, degraded, labels in tqdm(
        loader, desc=f"学習 epoch {epoch + 1}/{EPOCHS}"
    ):
        clean = clean.to(device, non_blocking=True)
        degraded = degraded.to(device, non_blocking=True)
        labels = labels.to(device, non_blocking=True)
        with torch.no_grad():
            clean_features = backbone(clean)
            degraded_features = backbone(degraded)
        for arm, head in heads.items():
            clean_hidden, clean_logits = head(clean_features)
            degraded_hidden, degraded_logits = head(degraded_features)
            loss = F.cross_entropy(clean_logits, labels) + F.cross_entropy(
                degraded_logits, labels
            )
            if arm in "BC":
                loss = loss + KL_WEIGHT * symmetric_kl(clean_logits, degraded_logits)
            if arm == "C":
                loss = loss + CONTRAST_WEIGHT * paired_contrastive(
                    clean_hidden, degraded_hidden, labels
                )
            optimizers[arm].zero_grad()
            loss.backward()
            optimizers[arm].step()
            totals[arm]["loss"] += loss.item() * len(labels)
            totals[arm]["clean"] += (clean_logits.argmax(1) == labels).sum().item()
            totals[arm]["degraded"] += (
                (degraded_logits.argmax(1) == labels).sum().item()
            )
            totals[arm]["n"] += len(labels)

    validation_correct = {arm: 0 for arm in "ABC"}
    validation_count = 0
    for head in heads.values():
        head.eval()
    with torch.inference_mode():
        for _, degraded, labels in tqdm(validation_loader, desc="検証"):
            degraded = degraded.to(device, non_blocking=True)
            labels = labels.to(device, non_blocking=True)
            features = backbone(degraded)
            for arm, head in heads.items():
                logits = head(features)[1]
                validation_correct[arm] += (logits.argmax(1) == labels).sum().item()
            validation_count += len(labels)
    for arm, head in heads.items():
        t = totals[arm]
        history[arm].append(
            {
                "epoch": epoch + 1,
                "loss": t["loss"] / t["n"],
                "train_clean_acc": t["clean"] / t["n"],
                "train_degraded_acc": t["degraded"] / t["n"],
                "validation_degraded_acc": validation_correct[arm] / validation_count,
            }
        )
        torch.save(
            {
                "protocol": PROTOCOL,
                "arm": arm,
                "model_id": MODEL_ID,
                "backbone_sha256": backbone_sha256,
                "manifest_sha256": report["manifest_sha256"],
                "source_audit_sha256": report["source_audit_sha256"],
                "epochs_completed": epoch + 1,
                "head": head.state_dict(),
                "history": history[arm],
                "torch_version": str(torch.__version__),
                "timm_version": str(timm.__version__),
            },
            BASE / f"pilot_v2_arm{arm}.pt",
        )
        print(arm, history[arm][-1])

# %% EVALUATE (run after the audited evaluation ledger and images are staged)
from google.colab import drive

drive.mount("/content/drive")

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import timm
import torch
import torch.nn.functional as F
from IPython.display import display
from scipy.stats import beta
from torch import nn
from torchvision import transforms
from tqdm.auto import tqdm

try:
    from pillow_heif import register_heif_opener
except ImportError as exc:
    raise RuntimeError(
        "先にColabで %pip install pillow-heif を実行してください"
    ) from exc
register_heif_opener()

BASE = Path("/content/drive/MyDrive/DETECTER-training")
EVAL_ROOT = Path("/content/drive/MyDrive/DETECTER-evaluation")
COHORT_ROOT, REAL_ROOT = EVAL_ROOT / "cohort", EVAL_ROOT / "iphone"
LEDGER = COHORT_ROOT / "ledger/evaluation-ledger-issue68-v2.jsonl"
MANIFEST = BASE / "train_verified.jsonl"
SOURCE_AUDIT = BASE / "source_audit.json"
MODEL_ID, PROTOCOL, EPOCHS = "vit_base_patch14_dinov2.lvd142m", "issue68-paired-v2", 3
SEED = 20260927
TARGETS = ("GPT Image 2.5", "Nano Banana 2 Lite")
CONDITIONS = ("clean", "resize1024_jpeg75", "sns_multihop")

if not LEDGER.is_file():
    raise FileNotFoundError(
        "条件・画像種別・独立撮影単位・指示文単位を監査した"
        " evaluation-ledger-issue68-v2.jsonl が必要です。"
    )
ledger = [json.loads(line) for line in LEDGER.read_text().splitlines() if line.strip()]
training = [
    json.loads(line) for line in MANIFEST.read_text().splitlines() if line.strip()
]
if len({row["image_id"] for row in ledger}) != len(ledger):
    raise ValueError("評価台帳のimage_idが重複しています")
ledger_groups = defaultdict(list)
for row in ledger:
    ledger_groups[row["source_group"]].append(row)
group_for_origin = {}
for group_id, members in ledger_groups.items():
    for field in (
        "label",
        "split",
        "generator",
        "image_kind",
        "capture_session_id",
        "prompt_group_id",
    ):
        if len({row.get(field) for row in members}) != 1:
            raise ValueError(f"{group_id}: 条件をまたいで {field} が一致しません")
    clean = [row for row in members if row.get("condition") == "clean"]
    if len(clean) != 1:
        raise ValueError(f"{group_id}: 基準となるclean画像が1枚必要です")
    origin = clean[0]["sha256"]
    if group_for_origin.setdefault(origin, group_id) != group_id:
        raise ValueError("同じclean画像が別の元画像群に登録されています")
    for row in members:
        if row.get("origin_sha256") != origin:
            raise ValueError(
                f"{row['image_id']}: clean画像と派生条件の元画像が違います"
            )
if not set(CONDITIONS) <= {row.get("condition") for row in ledger}:
    raise ValueError("clean、1024→JPEG Q75、実SNSの3評価条件が必要です")
for condition in CONDITIONS:
    if not any(
        row["split"] == "tuning"
        and row["label"] == "real"
        and row.get("condition") == condition
        for row in ledger
    ):
        raise ValueError(f"{condition}: 閾値調整用の実写がありません")
    if not any(
        row["split"] == "evaluation"
        and row["label"] == "real"
        and row.get("condition") == condition
        for row in ledger
    ):
        raise ValueError(f"{condition}: 評価用の実写がありません")
    for generator in TARGETS:
        if not any(
            row["split"] == "evaluation"
            and row["label"] == "generated"
            and row.get("generator") == generator
            and row.get("condition") == condition
            for row in ledger
        ):
            raise ValueError(f"{condition}/{generator}: 評価用の生成画像がありません")
for row in ledger:
    if row.get("condition") == "resize1024_jpeg75":
        history = row.get("history") or []
        if (
            len(history) != 2
            or history[-2].get("operation") != "resize"
            or history[-2].get("long_side") != 1024
            or history[-1].get("operation") != "jpeg"
            or history[-1].get("jpeg_quality") != 75
        ):
            raise ValueError(
                f"{row['image_id']}: 長辺1024→JPEG品質75の履歴がありません"
            )
    if row.get("condition") == "sns_multihop":
        receipt = row.get("platform_receipt") or {}
        hops = receipt.get("hops") or []
        if len(hops) < 2 or not all(
            all(
                hop.get(key)
                for key in (
                    "platform",
                    "upload_receipt",
                    "download_receipt",
                    "input_sha256",
                    "output_sha256",
                )
            )
            for hop in hops
        ):
            raise ValueError(
                f"{row['image_id']}: 実SNSの2ホップ以上の投稿・取得記録が必要です"
            )
        if any(
            hops[index]["output_sha256"] != hops[index + 1]["input_sha256"]
            for index in range(len(hops) - 1)
        ):
            raise ValueError(f"{row['image_id']}: 実SNSのホップが連結されていません")
        if hops[0]["input_sha256"] != row["origin_sha256"]:
            raise ValueError(f"{row['image_id']}: 実SNSの起点がclean画像ではありません")
        if hops[-1]["output_sha256"] != row["sha256"]:
            raise ValueError(
                f"{row['image_id']}: 最終ホップと評価画像のハッシュが違います"
            )
if any(not row.get("capture_session_id") for row in ledger if row["label"] == "real"):
    raise ValueError("実写行に監査済みの独立撮影単位が必要です")
if any(
    not row.get("prompt_group_id")
    for row in ledger
    if row["label"] == "generated" and row.get("generator") in TARGETS
):
    raise ValueError("対象生成器に指示文グループが必要です")
if not {"photo", "unknown"} <= {
    row.get("image_kind")
    for row in ledger
    if row["label"] == "real" and row["split"] == "evaluation"
}:
    raise ValueError("実写のphoto/unknown種別が未監査です")
for generator in TARGETS:
    if not any(
        row["split"] == "evaluation"
        and row["label"] == "generated"
        and row.get("generator") == generator
        and row.get("image_kind") == "photo"
        for row in ledger
    ):
        raise ValueError(f"{generator}: 写真種別の生成画像が未監査です")

tuning_real_rows = [
    row for row in ledger if row["split"] == "tuning" and row["label"] == "real"
]
evaluation_real_rows = [
    row for row in ledger if row["split"] == "evaluation" and row["label"] == "real"
]
if {row["source_group"] for row in tuning_real_rows} & {
    row["source_group"] for row in evaluation_real_rows
}:
    raise ValueError("同じ元画像群が閾値調整と評価の両方にあります")
if {row["capture_session_id"] for row in tuning_real_rows} & {
    row["capture_session_id"] for row in evaluation_real_rows
}:
    raise ValueError("同じ撮影セッションが閾値調整と評価の両方にあります")
if {row["origin_sha256"] for row in tuning_real_rows} & {
    row["origin_sha256"] for row in evaluation_real_rows
}:
    raise ValueError("同じ実写原画像のバイトが閾値調整と評価の両方にあります")
for name, selected_rows in (
    ("tuning", tuning_real_rows),
    ("evaluation", evaluation_real_rows),
):
    session_for_group = {
        row["source_group"]: row["capture_session_id"] for row in selected_rows
    }
    if len(set(session_for_group.values())) != len(session_for_group):
        raise ValueError(
            f"{name}: 独立性を主張するには撮影セッションごとに実写1群が必要です"
        )

train_hashes = {row["sha256"] for row in training}
if train_hashes & {row["sha256"] for row in ledger}:
    raise ValueError("学習・評価に同じ画像バイトが含まれます")
if {row["source_group"] for row in training} & {row["source_group"] for row in ledger}:
    raise ValueError("学習・評価に同じ元画像群が含まれます")

records = [
    row
    for row in ledger
    if row["split"] == "evaluation"
    or (row["split"] == "tuning" and row["label"] == "real")
]


def evaluation_path(row):
    path = row["path"]
    cohort_prefix = "/Users/nana/workspace/detecter-cohort/"
    photo_prefix = "/Volumes/Multimedia/iphone/"
    if path.startswith(cohort_prefix):
        return COHORT_ROOT / path.removeprefix(cohort_prefix)
    if path.startswith(photo_prefix):
        return REAL_ROOT / path.removeprefix(photo_prefix)
    raise ValueError(f"未対応の評価画像パス: {path}")


for row in tqdm(records, desc="評価画像を確認"):
    path = evaluation_path(row)
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("rb") as image_file:
        if hashlib.file_digest(image_file, "sha256").hexdigest() != row["sha256"]:
            raise ValueError(f"{row['image_id']}: 評価画像のSHA-256が違います")
    if row["condition"] == "resize1024_jpeg75":
        with Image.open(path) as image:
            if image.format != "JPEG" or max(image.size) != 1024:
                raise ValueError(
                    f"{row['image_id']}: 1024/Q75画像の形式または寸法が違います"
                )


class PilotHead(nn.Module):
    def __init__(self, width):
        super().__init__()
        self.norm = nn.LayerNorm(width)
        self.shared = nn.Linear(width, 256)
        self.classifier = nn.Linear(256, 2)

    def forward(self, features):
        hidden = F.gelu(self.shared(self.norm(features)))
        return hidden, self.classifier(hidden)


device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
backbone = timm.create_model(MODEL_ID, pretrained=True, num_classes=0).to(device).eval()
backbone.requires_grad_(False)
backbone_hash = hashlib.sha256()
for name, value in sorted(backbone.state_dict().items()):
    backbone_hash.update(name.encode())
    backbone_hash.update(value.detach().cpu().contiguous().numpy().tobytes())
backbone_sha256 = backbone_hash.hexdigest()
heads = {}
manifest_sha256 = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
source_audit_sha256 = hashlib.sha256(SOURCE_AUDIT.read_bytes()).hexdigest()
for arm in "ABC":
    checkpoint = torch.load(
        BASE / f"pilot_v2_arm{arm}.pt", map_location="cpu", weights_only=True
    )
    if (
        checkpoint["protocol"] != PROTOCOL
        or checkpoint["arm"] != arm
        or checkpoint["model_id"] != MODEL_ID
        or checkpoint["backbone_sha256"] != backbone_sha256
        or checkpoint["manifest_sha256"] != manifest_sha256
        or checkpoint["source_audit_sha256"] != source_audit_sha256
        or checkpoint["epochs_completed"] != EPOCHS
    ):
        raise ValueError(f"{arm}: 学習済みモデルの条件が一致しません")
    head = PilotHead(backbone.num_features).to(device)
    head.load_state_dict(checkpoint["head"])
    heads[arm] = head.eval()

preprocess = transforms.Compose(
    [
        transforms.Resize(518),
        transforms.CenterCrop(518),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ]
)
scores = {arm: {} for arm in "ABC"}
with torch.inference_mode():
    for start in tqdm(range(0, len(records), 32), desc="評価画像を採点"):
        batch = records[start : start + 32]
        images = []
        for row in batch:
            with Image.open(evaluation_path(row)) as source:
                images.append(
                    preprocess(ImageOps.exif_transpose(source).convert("RGB"))
                )
        features = backbone(torch.stack(images).to(device))
        for arm, head in heads.items():
            values = head(features)[1].softmax(1)[:, 1].cpu().tolist()
            scores[arm].update(
                (row["image_id"], float(value)) for row, value in zip(batch, values)
            )


def group_scores(arm):
    members = defaultdict(list)
    for row in records:
        members[(row["source_group"], row["condition"])].append(row)
    result = {}
    for key, group in members.items():
        for field in ("label", "split", "generator", "image_kind"):
            if len({row.get(field) for row in group}) != 1:
                raise ValueError(f"{key}: {field} が不一致です")
        label = group[0]["label"]
        values = [scores[arm][row["image_id"]] for row in group]
        result[key] = {
            "score": max(values) if label == "real" else min(values),
            "label": label,
            "split": group[0]["split"],
            "generator": group[0].get("generator"),
            "kind": group[0].get("image_kind"),
            "session": group[0].get("capture_session_id"),
            "prompt": group[0].get("prompt_group_id"),
        }
    return result


groups = {arm: group_scores(arm) for arm in "ABC"}
if set(groups["A"]) != set(groups["B"]) or set(groups["A"]) != set(groups["C"]):
    raise ValueError("A/B/Cで評価画像群が一致しません")


def upper_fpr95(fp, n):
    return 1.0 if fp == n else float(beta.ppf(0.95, fp + 1, n - fp))


def cluster_delta_ci(candidate, baseline, prompts):
    clusters = defaultdict(list)
    for index, prompt in enumerate(prompts):
        clusters[prompt].append(index)
    prompt_ids = list(clusters)
    rng = np.random.default_rng(SEED)
    estimates = []
    delta = np.asarray(candidate, dtype=float) - np.asarray(baseline, dtype=float)
    for _ in range(3000):
        sampled = rng.choice(prompt_ids, size=len(prompt_ids), replace=True)
        indices = [index for prompt in sampled for index in clusters[prompt]]
        estimates.append(float(delta[indices].mean()))
    return float(delta.mean()), *map(float, np.quantile(estimates, (0.025, 0.975)))


def cluster_tpr_ci(flags, prompts):
    clusters = defaultdict(list)
    for index, prompt in enumerate(prompts):
        clusters[prompt].append(index)
    prompt_ids = list(clusters)
    if all(flags):
        return float(beta.ppf(0.025, len(prompt_ids), 1)), 1.0
    if not any(flags):
        return 0.0, float(beta.ppf(0.975, 1, len(prompt_ids)))
    rng = np.random.default_rng(SEED)
    values = np.asarray(flags, dtype=float)
    estimates = []
    for _ in range(3000):
        sampled = rng.choice(prompt_ids, size=len(prompt_ids), replace=True)
        indices = [index for prompt in sampled for index in clusters[prompt]]
        estimates.append(float(values[indices].mean()))
    return tuple(map(float, np.quantile(estimates, (0.025, 0.975))))


results = []
for condition in CONDITIONS:
    for kind in ("overall", "photo", "unknown"):

        def selected(row, kind=kind):
            return kind == "overall" or row["kind"] == kind

        for fpr_target in (0.01, 0.001):
            thresholds = {}
            for arm in "ABC":
                tune = sorted(
                    row["score"]
                    for (source_group, cond), row in groups[arm].items()
                    if cond == condition
                    and row["split"] == "tuning"
                    and row["label"] == "real"
                )
                if tune:
                    allowed = math.floor(len(tune) * fpr_target)
                    thresholds[arm] = math.nextafter(tune[-allowed - 1], math.inf)
            if len(thresholds) != 3:
                raise ValueError(f"{condition}/{kind}: 調整用実写が不足しています")

            eval_real = {
                arm: {
                    source_group: row
                    for (source_group, cond), row in groups[arm].items()
                    if cond == condition
                    and row["split"] == "evaluation"
                    and row["label"] == "real"
                    and selected(row)
                }
                for arm in "ABC"
            }
            if not eval_real["A"]:
                raise ValueError(f"{condition}/{kind}: 評価用実写がありません")
            fpr = {}
            for arm in "ABC":
                fp_groups = {
                    source_group
                    for source_group, row in eval_real[arm].items()
                    if row["score"] >= thresholds[arm]
                }
                real_count = len(eval_real[arm])
                fp_count = len(fp_groups)
                fpr[arm] = {
                    "real_groups": real_count,
                    "fp_groups": fp_count,
                    "achieved_fpr": fp_count / real_count,
                    "fpr_upper95": upper_fpr95(fp_count, real_count),
                }

            for generator in TARGETS:
                target = {
                    arm: {
                        source_group: row
                        for (source_group, cond), row in groups[arm].items()
                        if cond == condition
                        and row["split"] == "evaluation"
                        and row["label"] == "generated"
                        and row["generator"] == generator
                        and selected(row)
                    }
                    for arm in "ABC"
                }
                ids = sorted(target["A"])
                if any(set(target[arm]) != set(ids) for arm in "BC"):
                    raise ValueError(
                        f"{condition}/{generator}/{kind}: A/B/Cの生成群が不一致です"
                    )
                flags = {
                    arm: [
                        target[arm][group]["score"] >= thresholds[arm] for group in ids
                    ]
                    for arm in "ABC"
                }
                prompts = [target["A"][group]["prompt"] for group in ids]
                for arm in "ABC":
                    n = len(ids)
                    tp = sum(flags[arm])
                    tpr_interval = (
                        cluster_tpr_ci(flags[arm], prompts) if n else (None, None)
                    )
                    delta = (
                        (None, None, None)
                        if arm == "A" or not n
                        else cluster_delta_ci(flags[arm], flags["A"], prompts)
                    )
                    actual = fpr[arm]
                    results.append(
                        {
                            "condition": condition,
                            "kind": kind,
                            "generator": generator,
                            "arm": arm,
                            "target_fpr": fpr_target,
                            "threshold": thresholds[arm],
                            **actual,
                            "generated_groups": n,
                            "detected": tp,
                            "prompt_clusters": len(set(prompts)),
                            "tpr": tp / n if n else None,
                            "tpr_ci95_low": tpr_interval[0],
                            "tpr_ci95_high": tpr_interval[1],
                            "delta_tpr_vs_A": delta[0],
                            "delta_ci95_low": delta[1],
                            "delta_ci95_high": delta[2],
                        }
                    )

result = pd.DataFrame(results)
display(result)
result.to_csv(BASE / "pilot_v2_issue68_evaluation.csv", index=False)
with (BASE / "pilot_v2_issue68_scores.jsonl").open("w") as output:
    for row in records:
        output.write(
            json.dumps(
                {
                    "image_id": row["image_id"],
                    "source_group": row["source_group"],
                    "condition": row["condition"],
                    "split": row["split"],
                    "label": row["label"],
                    "generator": row.get("generator"),
                    "image_kind": row.get("image_kind"),
                    "scores": {arm: scores[arm][row["image_id"]] for arm in "ABC"},
                },
                ensure_ascii=False,
            )
            + "\n"
        )
(BASE / "pilot_v2_issue68_evaluation_metadata.json").write_text(
    json.dumps(
        {
            "protocol": PROTOCOL,
            "evaluation_ledger_sha256": hashlib.sha256(LEDGER.read_bytes()).hexdigest(),
            "training_manifest_sha256": manifest_sha256,
            "source_audit_sha256": source_audit_sha256,
            "backbone_sha256": backbone_sha256,
            "group_policy": "real=max, generated=min within condition",
            "threshold_policy": "one condition-specific threshold from all tuning real groups; photo/unknown are breakdowns at the same threshold",
            "confidence_policy": "one real source group per audited capture session; exact one-sided FPR bound; prompt-cluster bootstrap for TPR/delta",
            "selection_policy": "exploratory multiple comparisons; no automatic Go decision",
        },
        ensure_ascii=False,
        indent=2,
    )
)
print("保存先:", BASE / "pilot_v2_issue68_evaluation.csv")
