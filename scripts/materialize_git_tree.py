#!/usr/bin/env python3

import argparse
import subprocess
import tarfile
import tempfile
from pathlib import Path


def materialize_git_tree(
    repository: Path,
    source: Path,
    destination: Path,
) -> None:
    repository = repository.resolve()
    source = source.resolve()
    destination = destination.resolve()
    try:
        source_relative = source.relative_to(repository)
    except ValueError as exc:
        raise ValueError(f"source must be inside {repository}: {source}") from exc
    if destination.exists():
        raise FileExistsError(f"destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix=".handbook-git-export-",
        dir=destination.parent,
    ) as temporary_directory:
        temporary = Path(temporary_directory)
        archive_path = temporary / "source.tar"
        extract_root = temporary / "extract"
        extract_root.mkdir()

        with archive_path.open("wb") as archive:
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repository),
                    "archive",
                    "--format=tar",
                    "HEAD",
                    source_relative.as_posix(),
                ],
                check=True,
                stdout=archive,
            )

        with tarfile.open(archive_path) as archive:
            archive.extractall(extract_root, filter="data")

        archived_source = extract_root / source_relative
        if not archived_source.is_dir():
            raise FileNotFoundError(
                f"{source_relative} is not a tracked directory at HEAD"
            )
        archived_source.rename(destination)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Materialize a directory from tracked files at Git HEAD."
    )
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()

    materialize_git_tree(
        repository=args.repository,
        source=args.source,
        destination=args.destination,
    )
    print(args.destination)


if __name__ == "__main__":
    main()
