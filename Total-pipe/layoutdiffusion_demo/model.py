import math
import torch
from torch import nn
from .config import DemoConfig, LABELS


def timestep_embedding(t, dim):
    half = dim // 2
    freqs = torch.exp(-math.log(10000) * torch.arange(half, device=t.device) / max(half - 1, 1))
    args = t.float()[:, None] * freqs[None]
    emb = torch.cat([torch.sin(args), torch.cos(args)], dim=-1)
    if dim % 2:
        emb = torch.nn.functional.pad(emb, (0, 1))
    return emb


class LayoutDenoiser(nn.Module):
    """Element-wise Transformer predicting clean discrete x/y/w/h tokens."""
    def __init__(self, cfg: DemoConfig):
        super().__init__()
        self.cfg = cfg
        # +1 coordinate token reserved for MASK.
        self.coord_emb = nn.ModuleList([nn.Embedding(cfg.num_bins + 1, cfg.d_model) for _ in range(4)])
        # Marks a coordinate the caller has pinned. Without this the token for a
        # pinned value is indistinguishable from the random-replacement noise in
        # ``corrupt``, so the model has no way to learn to treat it as a
        # constraint. Only applied when the flag is supplied, which keeps
        # checkpoints trained before this existed loadable and unchanged.
        self.known_emb = nn.Embedding(2, cfg.d_model)
        self.label_emb = nn.Embedding(len(LABELS), cfg.d_model)
        self.pos_emb = nn.Embedding(cfg.max_elements, cfg.d_model)
        self.time_mlp = nn.Sequential(
            nn.Linear(cfg.d_model, cfg.d_model), nn.SiLU(), nn.Linear(cfg.d_model, cfg.d_model)
        )
        layer = nn.TransformerEncoderLayer(
            d_model=cfg.d_model, nhead=cfg.nhead,
            dim_feedforward=cfg.dim_feedforward,
            dropout=cfg.dropout, batch_first=True, norm_first=True,
            activation="gelu",
        )
        self.transformer = nn.TransformerEncoder(layer, cfg.num_layers)
        self.norm = nn.LayerNorm(cfg.d_model)
        self.heads = nn.ModuleList([nn.Linear(cfg.d_model, cfg.num_bins) for _ in range(4)])

    def forward(self, labels, noisy_coords, t, valid_mask, known_mask=None):
        B, N = labels.shape
        h = self.label_emb(labels)
        for j in range(4):
            h = h + self.coord_emb[j](noisy_coords[..., j])
        if known_mask is not None:
            h = h + self.known_emb(known_mask.long()).sum(dim=2)
        pos = torch.arange(N, device=labels.device)[None].expand(B, N)
        h = h + self.pos_emb(pos)
        te = self.time_mlp(timestep_embedding(t, self.cfg.d_model))[:, None, :]
        h = h + te
        h = self.transformer(h, src_key_padding_mask=~valid_mask)
        h = self.norm(h)
        return torch.stack([head(h) for head in self.heads], dim=2)  # B,N,4,bins
