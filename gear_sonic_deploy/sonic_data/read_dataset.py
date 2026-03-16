#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd


def _load_episode_index(dataset_root: Path) -> pd.DataFrame:
    episode_files = sorted((dataset_root / "meta" / "episodes").glob("chunk-*/file-*.parquet"))
    if not episode_files:
        raise FileNotFoundError(f"No episode index parquet found under {dataset_root / 'meta' / 'episodes'}")
    frames = [pd.read_parquet(path) for path in episode_files]
    return pd.concat(frames, ignore_index=True)


def _load_data_file(dataset_root: Path, chunk_index: int, file_index: int) -> pd.DataFrame:
    path = dataset_root / "data" / f"chunk-{chunk_index:03d}" / f"file-{file_index:03d}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Data parquet not found: {path}")
    return pd.read_parquet(path)


def _describe_value(value) -> str:
    if hasattr(value, "shape"):
        return f"type={type(value).__name__}, shape={value.shape}"
    if isinstance(value, list):
        return f"type=list, len={len(value)}"
    return f"type={type(value).__name__}, value={value}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect sonic_data dataset parquet outputs.")
    parser.add_argument("dataset_root", help="Path to dataset root, e.g. outputs/g1_rgbd/<dataset>")
    parser.add_argument("--episode", type=int, default=0, help="Episode index to inspect in detail")
    args = parser.parse_args()

    dataset_root = Path(args.dataset_root).expanduser().resolve()
    if not dataset_root.exists():
        raise FileNotFoundError(f"Dataset root does not exist: {dataset_root}")

    episode_df = _load_episode_index(dataset_root)
    print(f"dataset_root: {dataset_root}")
    print(f"num_episodes: {len(episode_df)}")
    print()
    print("episodes:")
    print(episode_df[["episode_index", "length", "tasks", "data/chunk_index", "data/file_index"]].to_string(index=False))

    row = episode_df.loc[episode_df["episode_index"] == args.episode]
    if row.empty:
        print()
        print(f"episode {args.episode} not found; done.")
        return

    row = row.iloc[0]
    chunk_index = int(row["data/chunk_index"])
    file_index = int(row["data/file_index"])
    data_df = _load_data_file(dataset_root, chunk_index, file_index)

    print()
    print(f"inspect episode: {args.episode}")
    print(f"data parquet: data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet")
    print(f"num_rows: {len(data_df)}")
    print("columns:")
    for column in data_df.columns.tolist():
        print(f"  - {column}")

    if len(data_df) == 0:
        print("data parquet has no rows")
        return

    first_row = data_df.iloc[0]
    print()
    print("first row summary:")
    for key in [
        "observation.state",
        "action",
        "observation.eef_state",
        "action.eef",
        "observation.images.ego_view_depth",
        "teleop.navigate_command",
        "teleop.base_height_command",
    ]:
        if key in data_df.columns:
            print(f"  {key}: {_describe_value(first_row[key])}")

    if "videos/observation.images.ego_view/file_index" in row.index:
        print()
        print("video reference:")
        print(
            "  "
            f"videos/observation.images.ego_view/chunk-{int(row['videos/observation.images.ego_view/chunk_index']):03d}/"
            f"file-{int(row['videos/observation.images.ego_view/file_index']):03d}.mp4"
        )


if __name__ == "__main__":
    main()
