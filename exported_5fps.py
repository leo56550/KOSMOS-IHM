import os
import pandas as pd
import numpy as np
import cv2
from tqdm import tqdm

STATION = 11
fp = rf"D:\2_ASSETS\Dellec-07052026\KOSMOS"

#------------------

fp = os.path.join(fp,f"{STATION:04d}")
fpL = os.path.join(fp,f"{STATION:04d}.txt")
fpR = os.path.join(fp,f"{STATION:04d}_stereo.txt")
videoL = os.path.join(fp,f"{STATION:04d}.mp4")
videoR = os.path.join(fp,f"{STATION:04d}_stereo.mp4")


dfL = pd.read_csv(fpL, header=None, names=["tps"])
dfR = pd.read_csv(fpR, header=None, names=["tps"])

tL = dfL["tps"].values
tR = dfR["tps"].values

indices = range(0, len(tL), 5) # 24fps -> 5fps = 1/5 image
matches = []
for i in indices:
    t = tL[i]
    j = np.argmin(np.abs(tR - t))
    if tR[j]-tL[i]<21 : #24fps = 41ms --> Donc /2 => 20.5ms
        matches.append((i, j))
    else :
        print(tR[j]-tL[i])

capL = cv2.VideoCapture(videoL)
capR = cv2.VideoCapture(videoR)

os.makedirs(os.path.join(fp,"5FPS/LEFT"), exist_ok=True)
os.makedirs(os.path.join(fp,"5FPS/RIGHT"), exist_ok=True)

def save_frame(cap, frame_idx, path):
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ret, frame = cap.read()
    if ret:
        cv2.imwrite(path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    return ret

for k, (i, j) in tqdm(enumerate(matches),total=len(matches)):

    pathL = os.path.join(fp,f"5FPS/LEFT/{k:05d}.jpg")
    pathR = os.path.join(fp,f"5FPS/RIGHT/{k:05d}.jpg")

    okL = save_frame(capL, i, pathL)
    okR = save_frame(capR, j, pathR)