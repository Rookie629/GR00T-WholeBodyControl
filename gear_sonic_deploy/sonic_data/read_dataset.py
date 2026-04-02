#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pandas as pd


def _load_episode_index(dataset_root: Path) -> pd.DataFrame:
    jsonl_path = dataset_root / "meta" / "episodes.jsonl"
    if jsonl_path.exists():
        rows = []
        with jsonl_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        if not rows:
            raise FileNotFoundError(f"No episode rows found in {jsonl_path}")
        return pd.DataFrame(rows)

    episode_files = sorted((dataset_root / "meta" / "episodes").glob("chunk-*/file-*.parquet"))
    if not episode_files:
        raise FileNotFoundError(f"No episode metadata found under {dataset_root / 'meta'}")
    frames = [pd.read_parquet(path) for path in episode_files]
    return pd.concat(frames, ignore_index=True)


def _load_dataset_info(dataset_root: Path) -> dict:
    path = dataset_root / "meta" / "info.json"
    if not path.exists():
        raise FileNotFoundError(f"Dataset info not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_data_file(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Data parquet not found: {path}")
    return pd.read_parquet(path)


def _resolve_chunk_file_indices(info: dict, episode_index: int) -> tuple[int, int]:
    chunk_size = int(info.get("chunks_size", 1000))
    return divmod(int(episode_index), chunk_size)


def _build_data_file_path(dataset_root: Path, info: dict, episode_index: int) -> Path:
    chunk_index, file_index = _resolve_chunk_file_indices(info, episode_index)
    template = info.get("data_path")
    if template:
        path = dataset_root / template.format(
            chunk_index=chunk_index,
            file_index=file_index,
            episode_index=int(episode_index),
        )
        if path.exists():
            return path

    new_path = dataset_root / "data" / f"chunk-{chunk_index:03d}" / f"episode_{episode_index:06d}.parquet"
    if new_path.exists():
        return new_path
    return dataset_root / "data" / f"chunk-{chunk_index:03d}" / f"file-{file_index:03d}.parquet"


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

    info = _load_dataset_info(dataset_root)
    episode_df = _load_episode_index(dataset_root)
    print(f"dataset_root: {dataset_root}")
    print(f"num_episodes: {len(episode_df)}")
    print()
    print("episodes:")
    columns = ["episode_index", "length", "tasks"]
    if "data/chunk_index" in episode_df.columns and "data/file_index" in episode_df.columns:
        columns.extend(["data/chunk_index", "data/file_index"])
    print(episode_df[columns].to_string(index=False))

    row = episode_df.loc[episode_df["episode_index"] == args.episode]
    if row.empty:
        print()
        print(f"episode {args.episode} not found; done.")
        return

    row = row.iloc[0]
    episode_index = int(row["episode_index"])
    data_path = _build_data_file_path(dataset_root, info, episode_index)
    data_df = _load_data_file(data_path)

    print()
    print(f"inspect episode: {args.episode}")
    print(f"data parquet: {data_path.relative_to(dataset_root)}")
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

    chunk_index, file_index = _resolve_chunk_file_indices(info, episode_index)
    video_template = info.get("video_path")
    if video_template:
        video_path = video_template.format(
            chunk_index=chunk_index,
            file_index=file_index,
            episode_index=episode_index,
            video_key="observation.images.ego_view",
        )
        print()
        print("video reference:")
        print(f"  {video_path}")


if __name__ == "__main__":
    main()
