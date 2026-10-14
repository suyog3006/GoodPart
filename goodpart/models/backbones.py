"""Frozen feature extractors. Each returns dense patch features shaped (B, H, W, C)."""
from __future__ import annotations

import numpy as np
import torch
import torch.nn.functional as F

_MEAN = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
_STD = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)


def to_batch(images, size: int, device: str) -> torch.Tensor:
    """RGB uint8 arrays (H, W, 3) -> ImageNet-normalised (B, 3, size, size) on `device`."""
    x = torch.from_numpy(np.stack([np.asarray(im) for im in images])).to(device)
    x = x.permute(0, 3, 1, 2).float() / 255.0
    if x.shape[-1] != size or x.shape[-2] != size:
        x = F.interpolate(x, size=(size, size), mode="bilinear", align_corners=False, antialias=True)
    return (x - _MEAN.to(device)) / _STD.to(device)


class DinoV2:
    """DINOv2 ViT patch tokens, one L2-normalised vector per 14x14 patch."""

    def __init__(self, name: str = "facebook/dinov2-base", size: int = 672, device: str = "cuda",
                 dtype: torch.dtype = torch.bfloat16):
        from transformers import AutoModel

        self.size = size - size % 14
        self.device = device
        self.dtype = dtype if device.startswith("cuda") else torch.float32
        self.model = AutoModel.from_pretrained(name, torch_dtype=self.dtype).to(device).eval()
        self.name = f"{name}@{self.size}"

    @torch.no_grad()
    def __call__(self, images) -> torch.Tensor:
        x = to_batch(images, self.size, self.device).to(self.dtype)
        tokens = self.model(pixel_values=x).last_hidden_state
        tokens = tokens[:, -(self.size // 14) ** 2 :]  # patch tokens (skip CLS / register tokens)
        g = self.size // 14
        return F.normalize(tokens.float().reshape(x.shape[0], g, g, -1), dim=-1)


class WideResNet50:
    """PatchCore features: layer2 + upsampled layer3, each averaged over a 3x3 neighbourhood,
    then channel depth reduced to `dim` by adaptive average pooling (as in Roth et al.)."""

    def __init__(self, size: int = 320, device: str = "cuda", dim: int = 1024):
        import torchvision

        w = torchvision.models.Wide_ResNet50_2_Weights.IMAGENET1K_V1
        self.net = torchvision.models.wide_resnet50_2(weights=w).to(device).eval()
        self.size, self.device, self.dim = size, device, dim
        self.name = f"wide_resnet50_2@{size}"

    @torch.no_grad()
    def __call__(self, images) -> torch.Tensor:
        n = self.net
        x = to_batch(images, self.size, self.device)
        with torch.autocast("cuda", dtype=torch.bfloat16, enabled=self.device.startswith("cuda")):
            x = n.maxpool(n.relu(n.bn1(n.conv1(x))))
            l2 = n.layer2(n.layer1(x))
            l3 = n.layer3(l2)
        l2 = F.avg_pool2d(l2.float(), 3, 1, 1)
        l3 = F.avg_pool2d(l3.float(), 3, 1, 1)
        l3 = F.interpolate(l3, size=l2.shape[-2:], mode="bilinear", align_corners=False)
        f = torch.cat([l2, l3], 1).permute(0, 2, 3, 1)  # (B, H, W, 1536)
        b, h, w, c = f.shape
        f = F.adaptive_avg_pool1d(f.reshape(-1, 1, c), self.dim)
        return f.reshape(b, h, w, self.dim)
