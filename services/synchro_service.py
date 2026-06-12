import json
import pandas as pd
import numpy as np
import cv2


def get_rectification_maps(json_path):
    """Calcule et retourne les maps de rectification stéréo depuis un JSON de calibration."""
    with open(json_path, 'r') as f:
        calib = json.load(f)

    size = (calib["image_width"], calib["image_height"])

    K_L = np.array([[calib["fx_left"], 0, calib["cx_left"]],
                    [0, calib["fy_left"], calib["cy_left"]],
                    [0, 0, 1]], dtype=np.float64)
    K_R = np.array([[calib["fx_right"], 0, calib["cx_right"]],
                    [0, calib["fy_right"], calib["cy_right"]],
                    [0, 0, 1]], dtype=np.float64)

    D_L = np.array([calib["k1_left"], calib["k2_left"], calib["p1_left"],
                    calib["p2_left"], calib["k3_left"]], dtype=np.float64)
    D_R = np.array([calib["k1_right"], calib["k2_right"], calib["p1_right"],
                    calib["p2_right"], calib["k3_right"]], dtype=np.float64)

    R = np.array(calib["R"], dtype=np.float64).reshape(3, 3)
    T = np.array(calib["T"], dtype=np.float64).reshape(3, 1)

    R1, R2, P1, P2, Q, _, _ = cv2.stereoRectify(
        K_L, D_L, K_R, D_R, size, R, T,
        flags=cv2.CALIB_ZERO_DISPARITY, alpha=0
    )

    mapL_x, mapL_y = cv2.initUndistortRectifyMap(K_L, D_L, R1, P1, size, cv2.CV_32FC1)
    mapR_x, mapR_y = cv2.initUndistortRectifyMap(K_R, D_R, R2, P2, size, cv2.CV_32FC1)

    return (mapL_x, mapL_y), (mapR_x, mapR_y)


def get_synced_indices(fpL_txt, fpR_txt, target_fps=5, video_fps=25):
    """Retourne la liste des couples (index_L, index_R) synchronisés."""
    tL = pd.read_csv(fpL_txt, header=None, names=["tps"])["tps"].values
    tR = pd.read_csv(fpR_txt, header=None, names=["tps"])["tps"].values

    interval = int(video_fps / target_fps)
    matches = []

    for i in range(0, len(tL), interval):
        j = np.argmin(np.abs(tR - tL[i]))
        if abs(tR[j] - tL[i]) < 21:  # tolérance d'une demi-frame
            matches.append((i, j))

    return matches
