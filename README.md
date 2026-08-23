# Scanning Program

This scanning program supports three different imaging workflows:

1. [8 micron imaging (PicoScope)](#1-8-micron-imaging-picoscope)
2. [1064 nm optomechanical imaging (Keysight EXA)](#2-1064-nm-optomechanical-imaging-keysight-exa)
3. [FPGA imaging](#3-fpga-imaging)

## Adjust Optical Setup (before running any scan)

Note: when the chip is illuminated by white light, the yellow region is the high-reflectivity chromium region, and the black region is the low-reflectivity soda-lime glass region.

0. Open Kinesis on the computer and adjust positions to the following: X = 2.20 mm, Y = 2.20 mm, Z = 0.50 mm. Adjust x and y positions in small steps no bigger than 0.1 mm. Adjust z position in small steps no bigger than 0.01 mm.
1. Open the white light source and flip up the beam splitter. Open ThorCam on the computer to see the white light image. Adjust Z position to around 0.48 mm allows image to focus.
2. Adjust the position of the chip to the desired scanning position. The start position should be at the top-right corner of the pattern you want to scan. To see all patterns on the chip, view `Desktop\2026_3_12_ucla_imaging_mask` (a GDS file). The same pattern can have different sizes — the size marking at the bottom of each pattern (e.g., "300 um") indicates its size.
3. The note below applies only to focusing for EXA/FPGA imaging. To find the best start scan position for the 300 um UCLA letters: first go to the top-right corner and adjust the chip position so the visual image shows half yellow region, half black region. Carefully move the chip to the right until it is completely in the high-reflectivity region, while maintaining the chip's y position during this move — this is important for being able to scan the entire image. Results from scanning from this optimal position versus a lower position are shown below.
4. Make sure the pump laser driving the optomechanical device is on. If you haven't checked the EXA spectrum in several days, check it to ensure the optomechanical device is still at resonance.
5. After moving the chip, put the beam splitter down. Adjust Z position back to 0.5 mm.Connect the optical fiber extending from the collimator to the power meter. Make sure the power meter is examining wavelength at around 1060 nm.
6. Open the 1064 nm laser.
7. Check the power reading on the power meter. If it is around 15 microwatts, the optical system is aligned (power above 10 microwatts also works). Calibrate optics if needed.
8. Reconnect the optical fiber to the fiber connecting to the vacuum chamber.
9. Start the scan using one of the programs described below.

![Start position](start%20position.png)

*Optimal Y position for the start scan position. After you adjust it to this Y position, only adjust it in the x direction by hand, until the visual image shows you're completely in the high-reflectivity region.*

![Correct start f0_hz grid](CorrectStartf0_hz_grid.png)

*Image result obtained by positioning it in the correct initial position described above.*

![Incorrect start position](incorrect%20start%20position.png)

*Incorrect Y position for the start scan position. This is too low compared to the optimal start scan position and would cause the pattern below to be recorded.*

![Incorrect start f0_hz grid](IncorrectStartf0_hz_grid.png)

*Image result obtained from the incorrect initial position, where Y is too low.*


## 1. 8 micron imaging (PicoScope)

Data is acquired through a PicoScope 2204A connected to a commercial photodetector.

Steps to acquire and analyze data:

1. Change the output folder name in `test_picoscope.py`. The big folder that contains folders of all 8 um photodetector scan results is `C:\Users\wong_\Desktop\test_data_04\27`.
2. Adjust the start position, scan parameters, and data directory name in `Move_2D_picoscope.py`.
3. Save both files.
4. Run `Move_2D_picoscope.py` and wait for it to complete.
5. Change the input directory name in `analyze_0427.py` and run the program.
6. To recreate the image (graphing location vs. mean voltage), change the input data directory name and file name in `create_grid_file_0427.py`.

> **Note:** `Move_2D_norealtime.py` is the scanning program for 8 micron imaging without the real-time display.

## 2. 1064 nm optomechanical imaging (Keysight EXA)

Imaging is achieved by analyzing the shift in peak frequency, recorded by a Keysight EXA N9010A spectrum analyzer.

Steps to acquire and analyze data:

1. Change the output folder name in `testsaveTrace_keysight.py`. The big folder that contains folders of all EXA scan results is `C:\Users\wong_\Desktop\Keysight_EXA_N9010A`.
2. Adjust the scan parameters in `Move_2D_1064.py`.
3. Save both files.
4. Run `Move_2D_1064.py`.
5. To analyze the data and generate spectrum graphs and grid graphs (images), update the input data folder name in `peakfrequency.py` and run it.
6. Images of peak frequency by spatial position are saved in the `grid_graphs` folder inside the input data directory.

> **Note:** `Move_2D_1064_NoRealtime.py` is the 1064 nm device imaging program without a real-time display.

## 3. FPGA imaging

Steps to acquire and analyze data:

1. Adjust the output folder name in `Move_2D_FPGA.py`. The big folder that contains folders of all FPGA scan results is `C:\Users\wong_\Desktop\FPGA_scan_data`.
2. Adjust the scan parameters in `Move_2D_FPGA.py` — each step corresponds to 10 microns.
3. Enable or disable the live display, as needed.
4. Save the file.
5. Wait until the scan completes, then run the matching data analysis/graphing program:
   - If the acquired data is saved as a numpy array, run `create_grid_file_numpyFPGA.py`.
   - If the acquired data is saved as individual CSV files (one per position), run `create_grid_file_FPGA.py`.
