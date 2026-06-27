from __future__ import annotations
import argparse
import json
import uuid
from pathlib import Path
import numpy as np
from .autorec_data import load_matrix, save_metadata
from .autorec_model import AutoRec
from .config import MODELS_DIR
from .db import connect
def train_autorec(
    include_synthetic: bool = True,
    hidden_dim: int = 64,
    epochs: int = 80,
    lr: float = 1e-3,
    dropout: float = 0.10,
    model_dir: str | Path | None = None,
) -> dict:
    try:
        import torch
    except Exception as exc:
        raise RuntimeError("PyTorch is required. Install: pip install -r requirements-autorec.txt") from exc
    matrix, mask, user_to_idx, item_to_idx, users, items = load_matrix(include_synthetic=include_synthetic)
    if matrix.size == 0 or mask.sum() == 0:
        raise RuntimeError("No interaction matrix entries found. Log clicks/bookings/ratings first or use include_synthetic=True.")
    model_dir = Path(model_dir or MODELS_DIR)
    model_dir.mkdir(parents=True, exist_ok=True)
    x = torch.tensor(matrix, dtype=torch.float32)
    m = torch.tensor(mask, dtype=torch.float32)
    model = AutoRec(num_items=matrix.shape[1], hidden_dim=hidden_dim, dropout=dropout)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-5)
    last_loss = None
    for epoch in range(1, epochs + 1):
        model.train()
        optimizer.zero_grad()
        pred = model(x)
        loss = (((pred - x) * m) ** 2).sum() / m.sum().clamp_min(1.0)
        loss.backward()
        optimizer.step()
        last_loss = float(loss.detach().cpu().item())
    run_id = f"autorec_{uuid.uuid4().hex[:12]}"
    model_path = model_dir / f"{run_id}.pt"
    metadata_path = model_dir / f"{run_id}.metadata.json"
    torch.save(model.state_dict(), model_path)
    metrics = {
        "train_masked_mse": last_loss,
        "observed_density": float(mask.sum() / mask.size),
        "num_users": len(users),
        "num_items": len(items),
        "num_observed": int(mask.sum()),
    }
    save_metadata(
        metadata_path,
        users=users,
        items=items,
        config={"hidden_dim": hidden_dim, "dropout": dropout, "include_synthetic": include_synthetic},
        metrics=metrics,
    )
    with connect() as con:
        con.execute(
            """
            INSERT INTO autorec_training_runs(
              run_id, include_synthetic, num_users, num_items, num_observed,
              hidden_dim, epochs, learning_rate, train_loss, model_path, metadata_path, notes
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id, int(include_synthetic), len(users), len(items), int(mask.sum()), hidden_dim,
                epochs, lr, last_loss, str(model_path), str(metadata_path),
                "Synthetic rows are for demo only." if include_synthetic else "Real interactions only.",
            ),
        )
        con.execute("INSERT OR REPLACE INTO autorec_serving_config(config_key, config_value) VALUES ('active_run_id', ?)", (run_id,))
    return {"run_id": run_id, "model_path": str(model_path), "metadata_path": str(metadata_path), "metrics": metrics}
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--real-only", action="store_true", help="Use only non-synthetic interaction_events.")
    p.add_argument("--hidden-dim", type=int, default=64)
    p.add_argument("--epochs", type=int, default=80)
    p.add_argument("--lr", type=float, default=1e-3)
    args = p.parse_args()
    result = train_autorec(include_synthetic=not args.real_only, hidden_dim=args.hidden_dim, epochs=args.epochs, lr=args.lr)
    print(json.dumps(result, indent=2))
if __name__ == "__main__":
    main()
