from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from .autorec_data import load_matrix, load_metadata
from .autorec_model import AutoRec
from .db import connect


def get_active_run() -> dict[str, Any] | None:
    with connect() as con:
        run_id_row = con.execute("SELECT config_value FROM autorec_serving_config WHERE config_key='active_run_id'").fetchone()
        if not run_id_row or not run_id_row[0]:
            row = con.execute("SELECT * FROM autorec_training_runs ORDER BY created_at DESC LIMIT 1").fetchone()
        else:
            row = con.execute("SELECT * FROM autorec_training_runs WHERE run_id=?", (run_id_row[0],)).fetchone()
        return dict(row) if row else None


def predict_autorec_scores(user_id: str, top_n: int = 50) -> dict[int, float]:
    """Return predicted AutoRec scores for known users. Empty dict if model/user unavailable."""
    run = get_active_run()
    if not run:
        return {}
    try:
        import torch
    except Exception:
        return {}

    metadata = load_metadata(run["metadata_path"])
    users = metadata["users"]
    items = [int(x) for x in metadata["items"]]
    if user_id not in users:
        return {}
    user_idx = users.index(user_id)
    matrix, mask, _, _, _, _ = load_matrix(include_synthetic=bool(run["include_synthetic"]))
    if user_idx >= matrix.shape[0]:
        return {}
    hidden_dim = int(metadata["config"].get("hidden_dim", 64))
    dropout = float(metadata["config"].get("dropout", 0.10))
    model = AutoRec(num_items=len(items), hidden_dim=hidden_dim, dropout=dropout)
    state = torch.load(run["model_path"], map_location="cpu")
    model.load_state_dict(state)
    model.eval()
    with torch.no_grad():
        x = torch.tensor(matrix[user_idx:user_idx+1], dtype=torch.float32)
        pred = model(x).cpu().numpy().ravel()
    # Convert raw reconstruction to normalized 0..1 using sigmoid.
    pred = 1 / (1 + np.exp(-pred))
    # Do not strongly recommend already high-observed items unless they still rank high in hybrid.
    scores = {int(item): float(score) for item, score in zip(items, pred)}
    return dict(sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_n])

