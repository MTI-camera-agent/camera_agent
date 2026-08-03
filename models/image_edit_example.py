import sys
import time
from pathlib import Path

import requests


API_URL = "http://127.0.0.1:8000/edit"


def main():
    if len(sys.argv) < 4:
        print("用法：python request_edit.py 输入图片 输出图片 \"编辑指令\"")
        sys.exit(1)

    input_path = Path(sys.argv[1]).expanduser().resolve()
    output_path = Path(sys.argv[2]).expanduser().resolve()
    instruction = sys.argv[3]

    if not input_path.is_file():
        print(f"找不到输入图片：{input_path}")
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with requests.Session() as session:
        with input_path.open("rb") as f:
            start = time.perf_counter()

            response = session.post(
                API_URL,
                files={
                    "image": (input_path.name, f, "application/octet-stream")
                },
                data={
                    "instruction": instruction
                },
                timeout=1800,
            )

            total_time = time.perf_counter() - start

    response.raise_for_status()
    output_path.write_bytes(response.content)

    print(f"输出图片：{output_path}")
    print(f"客户端总耗时：{total_time:.3f} s")
    print(f"服务端耗时：{response.headers.get('X-Total-Time')}")


if __name__ == "__main__":
    main()