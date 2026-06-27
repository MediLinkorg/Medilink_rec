from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from .db import connect


def load_matrix(include_synthetic: bool = True) -> tuple[np.ndarray, np.ndarray, dict[str, int], dict[int, int], list[str], list[int]]:
    """Return matrix, mask, user_to_idx, item_to_idx, users, items.

    Matrix values are normalized to 0..1 from 0..5 interaction scores.
    """
    view = "v_autorec_matrix_entries" if include_synthetic else "v_autorec_matrix_entries_real"
    with connect() as con:
        rows = con.execute(f"SELECT user_id, doctor_cache_id, interaction_score FROM {view}").fetchall()
        users = [r[0] for r in con.execute("SELECT DISTINCT user_id FROM user_profiles ORDER BY user_id").fetchall()]
        items = [int(r[0]) for r in con.execute("SELECT doctor_cache_id FROM doctor_cache ORDER BY doctor_cache_id").fetchall()]
    user_to_idx = {u: i for i, u in enumerate(users)}
    item_to_idx = {it: j for j, it in enumerate(items)}
    matrix = np.zeros((len(users), len(items)), dtype=np.float32)
    mask = np.zeros_like(matrix, dtype=np.float32)
    for user_id, doctor_id, score in rows:
        if user_id in user_to_idx and int(doctor_id) in item_to_idx:
            i = user_to_idx[user_id]
            j = item_to_idx[int(doctor_id)]
            matrix[i, j] = min(5.0, max(0.0, float(score or 0.0))) / 5.0
            mask[i, j] = 1.0
    return matrix, mask, user_to_idx, item_to_idx, users, items


def save_metadata(path: str | Path, *, users: list[str], items: list[int], config: dict[str, Any], metrics: dict[str, Any]) -> None:
    data = {"users": users, "items": items, "config": config, "metrics": metrics}
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_metadata(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))

