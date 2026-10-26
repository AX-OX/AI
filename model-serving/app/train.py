"""Build the trusted local model artifact; never download or load user pickles."""

import argparse
from datetime import datetime, timezone
from pathlib import Path

import joblib
from sklearn.datasets import load_iris
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split

MODEL_VERSION = "iris-rf-v1"


def train(output: Path) -> dict:
    iris = load_iris()
    x_train, x_test, y_train, y_test = train_test_split(
        iris.data, iris.target, test_size=0.2, stratify=iris.target, random_state=42
    )
    model = RandomForestClassifier(n_estimators=50, random_state=42, n_jobs=1)
    model.fit(x_train, y_train)
    artifact = {
        "model": model,
        "version": MODEL_VERSION,
        "classes": iris.target_names.tolist(),
        "test_accuracy": float(model.score(x_test, y_test)),
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_samples": len(x_train),
        "test_samples": len(x_test),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, output)
    return artifact


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/iris.joblib"))
    args = parser.parse_args()
    artifact = train(args.output)
    print(f"Saved {artifact['version']} to {args.output}; test accuracy={artifact['test_accuracy']:.3f}")
