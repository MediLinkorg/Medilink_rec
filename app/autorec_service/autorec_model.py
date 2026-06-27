from __future__ import annotations

from dataclasses import dataclass

try:
    import torch
    import torch.nn as nn
except Exception:  # pragma: no cover
    torch = None
    nn = None


@dataclass
class AutoRecConfig:
    num_items: int
    hidden_dim: int = 64
    dropout: float = 0.10


if nn is not None:
    class AutoRec(nn.Module):
        """User-based AutoRec.

        Input: a user's sparse doctor-interaction vector.
        Output: reconstructed scores for all doctors.
        Loss must be masked so only observed entries contribute.
        """
        def __init__(self, num_items: int, hidden_dim: int = 64, dropout: float = 0.10):
            super().__init__()
            self.encoder = nn.Sequential(
                nn.Linear(num_items, hidden_dim),
                nn.Sigmoid(),
                nn.Dropout(dropout),
            )
            self.decoder = nn.Linear(hidden_dim, num_items)

        def forward(self, x):
            return self.decoder(self.encoder(x))
else:
    class AutoRec:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise RuntimeError("PyTorch is required. Install: pip install -r requirements-autorec.txt")

