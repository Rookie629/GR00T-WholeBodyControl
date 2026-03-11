from __future__ import annotations

from dataclasses import dataclass
import json
from math import ceil
from pathlib import Path
import shutil
from typing import Any, Optional

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from gear_sonic_deploy.sonic_data.dataset.video_writer import VideoWriter


SYSTEM_FEATURES = {
    "timestamp": {"dtype": "float64", "shape": (), "names": None},
    "frame_index": {"dtype": "int64", "shape": (), "names": None},
    "episode_index": {"dtype": "int64", "shape": (), "names": None},
    "index": {"dtype": "int64", "shape": (), "names": None},
    "task_index": {"dtype": "int64", "shape": (), "names": None},
}
STATS_KEYS = ("min", "max", "mean", "std", "count", "q01", "q10", "q50", "q90", "q99")


def _serialize_script_config(script_config) -> dict:
    if script_config is None:
        return {}
    if isinstance(script_config, dict):
        return script_config
    if hasattr(script_config, "to_dict"):
        return script_config.to_dict()
    raise TypeError(
        "script_config must be a dict, None, or an object exposing to_dict(). "
        f"Got {type(script_config)!r}."
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4)


def _normalize_shape(shape) -> list[int]:
    if shape in (None, ()):
        return []
    if isinstance(shape, int):
        return [shape]
    return [int(v) for v in shape]


def _dtype_to_arrow(dtype: str) -> pa.DataType:
    mapping = {
        "float64": pa.float64(),
        "float32": pa.float32(),
        "int64": pa.int64(),
        "int32": pa.int32(),
        "uint16": pa.uint16(),
        "uint8": pa.uint8(),
        "bool": pa.bool_(),
    }
    if dtype not in mapping:
        raise ValueError(f"Unsupported dtype: {dtype}")
    return mapping[dtype]


def _arrow_type_for_feature(feature: dict) -> pa.DataType:
    arrow_type = _dtype_to_arrow(feature["dtype"])
    for size in reversed(_normalize_shape(feature.get("shape"))):
        arrow_type = pa.list_(arrow_type, size)
    return arrow_type


def _python_value(value: Any):
    if isinstance(value, np.ndarray):
        if value.ndim == 0:
            return value.item()
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return value


def _round_trip_feature_spec(feature_name: str, spec: dict, fps: int) -> dict:
    out = {
        "dtype": spec["dtype"],
        "shape": _normalize_shape(spec.get("shape")),
        "names": spec.get("names"),
    }
    if spec["dtype"] == "video":
        height, width, channels = out["shape"]
        out["info"] = {
            "video.height": height,
            "video.width": width,
            "video.channels": channels,
            "video.codec": "h264",
            "video.pix_fmt": "yuv420p",
            "video.is_depth_map": False,
            "video.fps": fps,
            "has_audio": False,
        }
    elif feature_name.endswith("ego_view_depth"):
        out["info"] = {
            "storage_dtype": "uint16",
        }
    return out


def _build_info_features(features: dict, fps: int) -> dict:
    merged = dict(features)
    merged.update(SYSTEM_FEATURES)
    return {
        key: _round_trip_feature_spec(key, spec, fps)
        for key, spec in merged.items()
    }


def _safe_mb_size(paths: list[Path]) -> int:
    total_bytes = sum(path.stat().st_size for path in paths if path.exists())
    return int(ceil(total_bytes / (1024 * 1024))) if total_bytes > 0 else 0


def _stat_payload(values: list[Any], *, video: bool = False) -> dict[str, list]:
    if len(values) == 0:
        return {key: [0] for key in STATS_KEYS}

    array = np.asarray(values)
    if video:
        data = array.astype(np.float32) / 255.0
        reduce_axes = tuple(range(data.ndim - 1))
        reducer = lambda fn: np.asarray(fn(data, axis=reduce_axes), dtype=np.float64).reshape(-1, 1, 1)
    elif array.ndim <= 1:
        data = array.astype(np.float64)
        reducer = lambda fn: np.asarray([fn(data)], dtype=np.float64)
    elif array.ndim == 2:
        data = array.astype(np.float64)
        reducer = lambda fn: np.asarray(fn(data, axis=0), dtype=np.float64)
    else:
        # High-dimensional arrays such as depth maps would explode metadata size if we
        # kept per-pixel stats. Store reduced scalar stats instead.
        data = array.astype(np.float64).reshape(array.shape[0], -1)
        reducer = lambda fn: np.asarray([fn(data)], dtype=np.float64)

    def quantile(q: float) -> np.ndarray:
        if video:
            return np.asarray(np.quantile(data, q, axis=reduce_axes), dtype=np.float64).reshape(-1, 1, 1)
        if array.ndim <= 1:
            return np.asarray([np.quantile(data, q)], dtype=np.float64)
        if array.ndim == 2:
            return np.asarray(np.quantile(data, q, axis=0), dtype=np.float64)
        return np.asarray([np.quantile(data, q)], dtype=np.float64)

    return {
        "min": reducer(np.min).tolist(),
        "max": reducer(np.max).tolist(),
        "mean": reducer(np.mean).tolist(),
        "std": reducer(np.std).tolist(),
        "count": [int(array.shape[0])],
        "q01": quantile(0.01).tolist(),
        "q10": quantile(0.10).tolist(),
        "q50": quantile(0.50).tolist(),
        "q90": quantile(0.90).tolist(),
        "q99": quantile(0.99).tolist(),
    }


def _aggregate_episode_stats(records: list[dict], feature_name: str) -> Optional[dict[str, list]]:
    if not records:
        return None

    count_key = f"stats/{feature_name}/count"
    if count_key not in records[0]:
        return None

    weights = []
    mins = []
    maxs = []
    means = []
    stds = []
    quantiles: dict[str, list[np.ndarray]] = {key: [] for key in ("q01", "q10", "q50", "q90", "q99")}

    for row in records:
        weight = int(np.asarray(row[count_key]).reshape(-1)[0])
        weights.append(weight)
        mins.append(np.asarray(row[f"stats/{feature_name}/min"], dtype=np.float64))
        maxs.append(np.asarray(row[f"stats/{feature_name}/max"], dtype=np.float64))
        means.append(np.asarray(row[f"stats/{feature_name}/mean"], dtype=np.float64))
        stds.append(np.asarray(row[f"stats/{feature_name}/std"], dtype=np.float64))
        for key in quantiles:
            quantiles[key].append(np.asarray(row[f"stats/{feature_name}/{key}"], dtype=np.float64))

    total = sum(weights)
    if total == 0:
        return None

    mins_arr = np.stack(mins)
    maxs_arr = np.stack(maxs)
    means_arr = np.stack(means)
    stds_arr = np.stack(stds)
    weights_arr = np.asarray(weights, dtype=np.float64).reshape((-1,) + (1,) * (means_arr.ndim - 1))

    overall_mean = np.sum(means_arr * weights_arr, axis=0) / total
    overall_var = np.sum(
        weights_arr * (stds_arr**2 + (means_arr - overall_mean) ** 2),
        axis=0,
    ) / total

    aggregated = {
        "min": np.min(mins_arr, axis=0).tolist(),
        "max": np.max(maxs_arr, axis=0).tolist(),
        "mean": overall_mean.tolist(),
        "std": np.sqrt(np.maximum(overall_var, 0.0)).tolist(),
        "count": [total],
    }
    for key, values in quantiles.items():
        arr = np.stack(values)
        aggregated[key] = (np.sum(arr * weights_arr, axis=0) / total).tolist()
    return aggregated


@dataclass
class DataCollectionInfo:
    lower_body_policy: Optional[str] = None
    wbc_model_path: Optional[str] = None
    teleoperator_username: Optional[str] = None
    support_operator_username: Optional[str] = None
    robot_type: Optional[str] = None
    robot_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "lower_body_policy": self.lower_body_policy,
            "wbc_model_path": self.wbc_model_path,
            "teleoperator_username": self.teleoperator_username,
            "support_operator_username": self.support_operator_username,
            "robot_type": self.robot_type,
            "robot_id": self.robot_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DataCollectionInfo":
        return cls(**data)


class Gr00tDatasetMetadata:
    MODALITY_CONFIG_REL_PATH = Path("meta/modality.json")
    INFO_REL_PATH = Path("meta/info.json")
    STATS_REL_PATH = Path("meta/stats.json")
    TASKS_REL_PATH = Path("meta/tasks.parquet")
    EPISODES_REL_DIR = Path("meta/episodes")

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.repo_id = "local/sonic_dataset"
        self.local_files_only = True
        self._load()

    def _load(self) -> None:
        with (self.root / self.INFO_REL_PATH).open("r", encoding="utf-8") as f:
            self.info = json.load(f)
        with (self.root / self.MODALITY_CONFIG_REL_PATH).open("r", encoding="utf-8") as f:
            self.modality_config = json.load(f)

        self.features = self.info.get("collector_features", {})
        self.video_keys = [key for key, spec in self.features.items() if spec["dtype"] == "video"]
        self.chunk_size = int(self.info.get("chunks_size", 1000))
        self.fps = int(self.info["fps"])

        self.tasks_by_index: list[str] = []
        self.task_to_index: dict[str, int] = {}
        self._load_tasks()
        self.episode_records = self._load_episode_records()
        self.discarded_episode_indices = list(self.info.get("discarded_episode_indices", []))
        self.next_episode_index = self._compute_next_episode_index()

    @classmethod
    def create(
        cls,
        *,
        root: str | Path,
        fps: int,
        features: dict,
        modality_config: dict,
        script_config: dict,
        data_collection_info: DataCollectionInfo,
        robot_type: str | None = None,
        upload_bucket_path: str | None = None,
    ) -> "Gr00tDatasetMetadata":
        root_path = Path(root)
        (root_path / "meta").mkdir(parents=True, exist_ok=True)
        (root_path / "data").mkdir(parents=True, exist_ok=True)
        (root_path / "videos").mkdir(parents=True, exist_ok=True)

        info = {
            "codebase_version": "v3.0",
            "robot_type": robot_type or data_collection_info.robot_type or "g1",
            "fps": int(fps),
            "chunks_size": 1000,
            "splits": {"train": "0:0"},
            "data_path": "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet",
            "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4",
            "total_episodes": 0,
            "total_frames": 0,
            "total_tasks": 0,
            "total_videos": 0,
            "data_files_size_in_mb": 0,
            "video_files_size_in_mb": 0,
            "features": _build_info_features(features, int(fps)),
            "collector_features": features,
            "script_config": script_config,
            "data_collection_info": data_collection_info.to_dict(),
            "discarded_episode_indices": [],
        }
        if upload_bucket_path is not None:
            info["upload_bucket_path"] = upload_bucket_path

        _write_json(root_path / cls.INFO_REL_PATH, info)
        _write_json(root_path / cls.MODALITY_CONFIG_REL_PATH, modality_config)
        _write_json(root_path / cls.STATS_REL_PATH, {})

        meta = cls(root_path)
        meta._rewrite_tasks_parquet()
        return meta

    def _compute_next_episode_index(self) -> int:
        indices = [row["episode_index"] for row in self.episode_records]
        indices.extend(self.discarded_episode_indices)
        return (max(indices) + 1) if indices else 0

    def _load_tasks(self) -> None:
        path = self.root / self.TASKS_REL_PATH
        if not path.exists():
            return
        table = pq.read_table(path)
        tasks = table["__index_level_0__"].to_pylist()
        indices = table["task_index"].to_pylist()
        for task, idx in zip(tasks, indices):
            self.task_to_index[task] = int(idx)
        self.tasks_by_index = [task for task, _ in sorted(self.task_to_index.items(), key=lambda item: item[1])]

    def _load_episode_records(self) -> list[dict]:
        rows: list[dict] = []
        for path in sorted((self.root / self.EPISODES_REL_DIR).glob("chunk-*/file-*.parquet")):
            rows.extend(pq.read_table(path).to_pylist())
        return rows

    def _rewrite_tasks_parquet(self) -> None:
        rows = [
            {"task_index": idx, "__index_level_0__": task}
            for idx, task in enumerate(self.tasks_by_index)
        ]
        path = self.root / self.TASKS_REL_PATH
        if rows:
            pq.write_table(pa.Table.from_pylist(rows), path)
        else:
            pq.write_table(
                pa.table(
                    {
                        "task_index": pa.array([], type=pa.int64()),
                        "__index_level_0__": pa.array([], type=pa.string()),
                    }
                ),
                path,
            )

    def get_task_index(self, task: str) -> int:
        if task not in self.task_to_index:
            task_index = len(self.tasks_by_index)
            self.task_to_index[task] = task_index
            self.tasks_by_index.append(task)
            self._rewrite_tasks_parquet()
            self.info["total_tasks"] = len(self.tasks_by_index)
            self.save_info()
        return self.task_to_index[task]

    def get_chunk_file_indices(self, episode_index: int) -> tuple[int, int]:
        return divmod(episode_index, self.chunk_size)

    def get_data_file_path(self, episode_index: int) -> Path:
        chunk_index, file_index = self.get_chunk_file_indices(episode_index)
        return Path("data") / f"chunk-{chunk_index:03d}" / f"file-{file_index:03d}.parquet"

    def get_video_file_path(self, episode_index: int, video_key: str) -> Path:
        chunk_index, file_index = self.get_chunk_file_indices(episode_index)
        return Path("videos") / video_key / f"chunk-{chunk_index:03d}" / f"file-{file_index:03d}.mp4"

    def get_episode_file_path(self, chunk_index: int) -> Path:
        return self.EPISODES_REL_DIR / f"chunk-{chunk_index:03d}" / "file-000.parquet"

    def append_episode_record(self, record: dict) -> None:
        self.episode_records.append(record)
        chunk_index = int(record["meta/episodes/chunk_index"])
        path = self.root / self.get_episode_file_path(chunk_index)
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = [row for row in self.episode_records if int(row["meta/episodes/chunk_index"]) == chunk_index]
        pq.write_table(pa.Table.from_pylist(rows), path)

    def save_stats(self, stats: dict) -> None:
        _write_json(self.root / self.STATS_REL_PATH, stats)

    def save_info(self) -> None:
        _write_json(self.root / self.INFO_REL_PATH, self.info)


class Gr00tDataExporter:
    def __init__(self, *, meta: Gr00tDatasetMetadata, task: str, vcodec: str = "h264"):
        self.meta = meta
        self.task = task
        self.vcodec = vcodec
        self.features = meta.features
        self.episode_buffer = self.create_episode_buffer(meta.next_episode_index)
        self.video_writers = self.create_video_writer()

    @property
    def root(self) -> Path:
        return self.meta.root

    @property
    def video_keys(self) -> list[str]:
        return self.meta.video_keys

    @classmethod
    def create(
        cls,
        save_root: str | Path,
        fps: int,
        features: dict,
        modality_config: dict,
        task: str,
        script_config=None,
        data_collection_info: DataCollectionInfo = DataCollectionInfo(),
        robot_type: str | None = None,
        tolerance_s: float = 1e-4,
        vcodec: str = "h264",
        overwrite_existing: bool = False,
        upload_bucket_path: str | None = None,
    ) -> "Gr00tDataExporter":
        del tolerance_s  # kept for CLI compatibility
        root = Path(save_root)
        if overwrite_existing and root.exists():
            shutil.rmtree(root)

        if root.exists():
            meta = Gr00tDatasetMetadata(root)
        else:
            meta = Gr00tDatasetMetadata.create(
                root=root,
                fps=fps,
                features=features,
                modality_config=modality_config,
                script_config=_serialize_script_config(script_config),
                data_collection_info=data_collection_info,
                robot_type=robot_type,
                upload_bucket_path=upload_bucket_path,
            )

        return cls(meta=meta, task=task, vcodec=vcodec)

    def create_episode_buffer(self, episode_index: int) -> dict:
        buffer = {"size": 0, "episode_index": episode_index, "task": [], "frame_index": [], "timestamp": []}
        for key in self.features:
            buffer[key] = []
        return buffer

    def create_video_writer(self) -> dict[str, VideoWriter]:
        writers: dict[str, VideoWriter] = {}
        episode_index = int(self.episode_buffer["episode_index"])
        for key in self.video_keys:
            rel_path = self.meta.get_video_file_path(episode_index, key)
            abs_path = self.root / rel_path
            shape = _normalize_shape(self.features[key]["shape"])
            height, width = shape[:2]
            writers[key] = VideoWriter(
                output_path=str(abs_path),
                width=width,
                height=height,
                fps=self.meta.fps,
                codec=self.vcodec,
            )
        return writers

    def add_frame(self, frame: dict) -> None:
        frame_index = int(self.episode_buffer["size"])
        timestamp = float(frame.get("timestamp", frame_index / float(self.meta.fps)))

        self.episode_buffer["frame_index"].append(frame_index)
        self.episode_buffer["timestamp"].append(timestamp)
        self.episode_buffer["task"].append(frame.get("task", self.task))

        for key, spec in self.features.items():
            if key not in frame:
                raise ValueError(f"Missing feature '{key}' in frame data.")
            value = np.asarray(frame[key])
            if spec["dtype"] == "video":
                rgb = value.astype(np.uint8)
                self.video_writers[key].add_frame(rgb)
                self.episode_buffer[key].append(rgb.copy())
            else:
                self.episode_buffer[key].append(value.copy())

        self.episode_buffer["size"] += 1

    def _reset_after_episode(self, next_episode_index: int) -> None:
        self.episode_buffer = self.create_episode_buffer(next_episode_index)
        self.meta.next_episode_index = next_episode_index
        self.video_writers = self.create_video_writer()

    def _cancel_video_writers(self) -> None:
        for writer in self.video_writers.values():
            writer.cancel()
        self.video_writers = {}

    def _stop_video_writers(self) -> dict[str, str]:
        rel_paths: dict[str, str] = {}
        for key, writer in self.video_writers.items():
            writer.stop()
            rel_paths[key] = str(self.meta.get_video_file_path(int(self.episode_buffer["episode_index"]), key))
        self.video_writers = {}
        return rel_paths

    def _write_data_parquet(self, episode_index: int, data_columns: dict[str, Any]) -> Path:
        rel_path = self.meta.get_data_file_path(episode_index)
        abs_path = self.root / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)

        arrays = []
        names = []
        for key, values in data_columns.items():
            if key in self.features:
                spec = self.features[key]
            else:
                spec = SYSTEM_FEATURES[key]
            names.append(key)
            arrays.append(
                pa.array([_python_value(value) for value in values], type=_arrow_type_for_feature(spec))
            )
        pq.write_table(pa.Table.from_arrays(arrays, names=names), abs_path)
        return rel_path

    def _compute_episode_stats(self, data_columns: dict[str, Any]) -> dict[str, dict[str, list]]:
        stats = {}
        for key, values in data_columns.items():
            is_video = key in self.video_keys
            stats[key] = _stat_payload(values, video=is_video)
        return stats

    def _build_episode_record(
        self,
        *,
        episode_index: int,
        episode_length: int,
        tasks: list[str],
        data_rel_path: Path,
        video_rel_paths: dict[str, str],
        episode_stats: dict[str, dict[str, list]],
        dataset_from_index: int,
        dataset_to_index: int,
    ) -> dict:
        chunk_index, data_file_index = self.meta.get_chunk_file_indices(episode_index)
        record = {
            "episode_index": episode_index,
            "tasks": tasks,
            "length": episode_length,
            "data/chunk_index": chunk_index,
            "data/file_index": data_file_index,
            "dataset_from_index": dataset_from_index,
            "dataset_to_index": dataset_to_index,
            "meta/episodes/chunk_index": chunk_index,
            "meta/episodes/file_index": 0,
        }
        for video_key in self.video_keys:
            video_chunk_index, video_file_index = self.meta.get_chunk_file_indices(episode_index)
            record[f"videos/{video_key}/chunk_index"] = video_chunk_index
            record[f"videos/{video_key}/file_index"] = video_file_index
            record[f"videos/{video_key}/from_timestamp"] = 0.0
            record[f"videos/{video_key}/to_timestamp"] = (episode_length - 1) / float(self.meta.fps)
        for feature_name, feature_stats in episode_stats.items():
            for stat_key, stat_value in feature_stats.items():
                record[f"stats/{feature_name}/{stat_key}"] = stat_value
        return record

    def _aggregate_dataset_stats(self) -> dict[str, dict[str, list]]:
        stats = {}
        feature_names = list(self.features.keys()) + list(SYSTEM_FEATURES.keys())
        for feature_name in feature_names:
            aggregated = _aggregate_episode_stats(self.meta.episode_records, feature_name)
            if aggregated is not None:
                stats[feature_name] = aggregated
        return stats

    def _update_info(self) -> None:
        data_files = sorted((self.root / "data").glob("chunk-*/file-*.parquet"))
        video_files = sorted((self.root / "videos").glob("*/*/*.mp4"))
        self.meta.info["total_episodes"] = len(self.meta.episode_records)
        self.meta.info["total_frames"] = sum(int(row["length"]) for row in self.meta.episode_records)
        self.meta.info["total_tasks"] = len(self.meta.tasks_by_index)
        self.meta.info["total_videos"] = len(video_files)
        self.meta.info["data_files_size_in_mb"] = _safe_mb_size(data_files)
        self.meta.info["video_files_size_in_mb"] = _safe_mb_size(video_files)
        self.meta.info["splits"] = {"train": f"0:{len(self.meta.episode_records)}"}
        self.meta.info["discarded_episode_indices"] = list(self.meta.discarded_episode_indices)
        self.meta.save_info()

    def save_episode(self) -> None:
        if int(self.episode_buffer["size"]) == 0:
            return

        episode_index = int(self.episode_buffer["episode_index"])
        episode_length = int(self.episode_buffer["size"])
        tasks = list(dict.fromkeys(self.episode_buffer["task"]))
        dataset_from_index = int(self.meta.info.get("total_frames", 0))
        dataset_to_index = dataset_from_index + episode_length

        task_indices = np.asarray(
            [self.meta.get_task_index(task) for task in self.episode_buffer["task"]],
            dtype=np.int64,
        )
        data_columns = {
            key: list(values)
            for key, values in self.episode_buffer.items()
            if key in self.features
        }
        data_columns.update(
            {
                "timestamp": np.asarray(self.episode_buffer["timestamp"], dtype=np.float64),
                "frame_index": np.asarray(self.episode_buffer["frame_index"], dtype=np.int64),
                "episode_index": np.full((episode_length,), episode_index, dtype=np.int64),
                "index": np.arange(dataset_from_index, dataset_to_index, dtype=np.int64),
                "task_index": task_indices,
            }
        )

        data_rel_path = self._write_data_parquet(episode_index, {k: v for k, v in data_columns.items() if k not in self.video_keys})
        video_rel_paths = self._stop_video_writers()
        episode_stats = self._compute_episode_stats(data_columns)
        record = self._build_episode_record(
            episode_index=episode_index,
            episode_length=episode_length,
            tasks=tasks,
            data_rel_path=data_rel_path,
            video_rel_paths=video_rel_paths,
            episode_stats=episode_stats,
            dataset_from_index=dataset_from_index,
            dataset_to_index=dataset_to_index,
        )
        self.meta.append_episode_record(record)
        self.meta.save_stats(self._aggregate_dataset_stats())
        self._update_info()
        self._reset_after_episode(episode_index + 1)

    def save_episode_as_discarded(self) -> None:
        if int(self.episode_buffer["size"]) == 0:
            return
        episode_index = int(self.episode_buffer["episode_index"])
        self._cancel_video_writers()
        self.meta.discarded_episode_indices.append(episode_index)
        self._update_info()
        self._reset_after_episode(episode_index + 1)
