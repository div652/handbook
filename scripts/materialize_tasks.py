#!/usr/bin/env python3

import argparse
import shutil
from pathlib import Path

if __package__:
    from .materialize_git_tree import materialize_git_tree
else:
    from materialize_git_tree import materialize_git_tree


def materialize_tasks(
    repository: Path,
    source: Path,
    destination: Path,
    base_image: str,
    expected_count: int,
) -> None:
    if not base_image or any(character.isspace() for character in base_image):
        raise ValueError(f"invalid Docker image reference: {base_image!r}")
    materialize_git_tree(repository, source, destination)
    try:
        dockerfiles = sorted(destination.glob("*/environment/Dockerfile"))
        task_files = sorted(destination.glob("*/task.toml"))
        if len(dockerfiles) != expected_count or len(task_files) != expected_count:
            raise ValueError(
                f"expected {expected_count} tasks and Dockerfiles, found "
                f"{len(task_files)} tasks and {len(dockerfiles)} Dockerfiles"
            )

        for dockerfile in dockerfiles:
            lines = dockerfile.read_text().splitlines(keepends=True)
            first_line = lines[0].rstrip("\r\n") if lines else ""
            if first_line != "FROM handbook_base":
                raise ValueError(
                    f"{dockerfile} must start with 'FROM handbook_base'; "
                    f"found {first_line!r}"
                )
            newline = "\n" if lines[0].endswith("\n") else ""
            lines[0] = f"FROM {base_image}{newline}"
            dockerfile.write_text("".join(lines))
    except BaseException:
        shutil.rmtree(destination)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Export tracked HANDBOOK tasks and pin every task to one base image."
        )
    )
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--base-image", required=True)
    parser.add_argument("--expected-count", type=int, default=65)
    args = parser.parse_args()

    materialize_tasks(
        repository=args.repository,
        source=args.source,
        destination=args.destination,
        base_image=args.base_image,
        expected_count=args.expected_count,
    )
    print(args.destination)


if __name__ == "__main__":
    main()
