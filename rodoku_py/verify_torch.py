import platform

import torch


def main() -> None:
    print("platform:", platform.platform())
    print("torch_version:", torch.__version__)
    print("cuda_available:", torch.cuda.is_available())

    x = torch.rand(2, 3)
    y = x @ x.t()
    print("x:", x)
    print("y:", y)


if __name__ == "__main__":
    main()

