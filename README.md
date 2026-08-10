# Scanning Program

This scanning program supports two different imaging workflows:

1. [8 micron imaging (PicoScope)](#1-8-micron-imaging-picoscope)
2. [1064 nm optomechanical imaging (Keysight EXA)](#2-1064-nm-optomechanical-imaging-keysight-exa)

## 1. 8 micron imaging (PicoScope)

Data is acquired through a PicoScope 2204A connected to a commercial photodetector.

Steps to acquire and analyze data:

1. Change the output folder name in `test_picoscope.py`.
2. Adjust the start position, scan parameters, and data directory name in `Move_2D_picoscope.py`.
3. Save both files.
4. Run `Move_2D_picoscope.py` and wait for it to complete.
5. Change the input directory name in `analyze_0427.py` and run the program.
6. To recreate the image (graphing location vs. mean voltage), change the input data directory name and file name in `create_grid_file_0427.py`.

> **Note:** `Move_2D_norealtime.py` is the scanning program for 8 micron imaging without the real-time display.

## 2. 1064 nm optomechanical imaging (Keysight EXA)

Imaging is achieved by analyzing the shift in peak frequency, recorded by a Keysight EXA N9010A spectrum analyzer.

Steps to acquire and analyze data:

1. Change the output folder name in `testsaveTrace_keysight.py`.
2. Adjust the scan parameters in `Move_2D_1064.py`.
3. Save both files.
4. Run `Move_2D_1064.py`.
5. To analyze the data and generate spectrum graphs and grid graphs (images), update the input data folder name in `peakfrequency.py` and run it.
6. Images of peak frequency by spatial position are saved in the `grid_graphs` folder inside the input data directory.

> **Note:** `Move_2D_1064_NoRealtime.py` is the 1064 nm device imaging program without a real-time display.