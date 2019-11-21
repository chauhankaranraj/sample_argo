import numpy as np


if __name__ == "__main__":
    randarr = np.random.rand(2, 2)
    print("Saving this array:\n", randarr)
    np.save("/mnt/vol/data.npy", randarr)
