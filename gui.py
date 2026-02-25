"""
Multi-Sensor Dashboard with Radar Visualization
Each section has auto/manual control with separate Device EUIs
"""

import tkinter as tk
from tkinter import ttk
import argparse
import os
import threading
import time
import math
from typing import Callable
from functools import partial

import matplotlib
matplotlib.use('TkAgg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import numpy as np

import sensor_service



# Global Device EUI Defaults
HUMIDITY_TEMP_EUI = "8695311000942380"
TILT_ACC_EUI = "8695311000942380"
WATER_LEVEL_EUI = "8695311000942380"
MMWAVE_EUI = "8695311001412450"


class SensorDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("Multi-Sensor Dashboard with Radar")
        self.root.geometry("1000x750")

        style = ttk.Style()
        style.theme_use("clam")

        # Auto/Manual states for each section
        self.ht_auto = False
        self.ta_auto = False
        self.wl_auto = False
        self.mmwave_auto = False

        self.poll_interval = 5

        # Create main container
        main_container = ttk.Frame(root)
        main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Left panel (sensor data)
        left_panel = ttk.Frame(main_container, width=700)
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(0, 10))

        # Right panel (radar visualization)
        right_panel = ttk.Frame(main_container)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # Create sections
        self.create_humidity_temp_section(left_panel)
        self.create_tilt_acc_section(left_panel)
        self.create_water_level_section(left_panel)

        # Create radar visualization
        self.create_radar_section(right_panel)

        # mmWave target data storage
        self.mmwave_targets = {}

        # Start polling threads
        self.start_all_polling_threads()

    def create_humidity_temp_section(self, parent):
        frame = ttk.LabelFrame(parent, text="Humidity & Temperature", padding="10")
        frame.pack(fill=tk.X, pady=5)
        frame.columnconfigure(2, weight=1)

        # Device EUI
        ttk.Label(frame, text="Device EUI:").grid(row=0, column=0, sticky=tk.W, padx=5)
        self.ht_eui_entry = ttk.Entry(frame, width=30)
        self.ht_eui_entry.grid(row=0, column=1, columnspan=2, sticky=(tk.W, tk.E), padx=5, pady=2)
        self.ht_eui_entry.insert(0, HUMIDITY_TEMP_EUI)

        # Data fields
        ttk.Label(frame, text="Temperature:").grid(row=1, column=0, sticky=tk.W, padx=5)
        self.ht_temp = ttk.Label(frame, text="--", font=('Arial', 11, 'bold'))
        self.ht_temp.grid(row=1, column=1, sticky=tk.W, padx=5)

        ttk.Label(frame, text="Humidity:").grid(row=2, column=0, sticky=tk.W, padx=5)
        self.ht_humidity = ttk.Label(frame, text="--", font=('Arial', 11, 'bold'))
        self.ht_humidity.grid(row=2, column=1, sticky=tk.W, padx=5)

        ttk.Label(frame, text="Dewpoint:").grid(row=3, column=0, sticky=tk.W, padx=5)
        self.ht_dewpoint = ttk.Label(frame, text="--", font=('Arial', 11, 'bold'))
        self.ht_dewpoint.grid(row=3, column=1, sticky=tk.W, padx=5)

        ttk.Label(frame, text="CRC:").grid(row=4, column=0, sticky=tk.W, padx=5)
        self.ht_crc = ttk.Label(frame, text="--", foreground="gray")
        self.ht_crc.grid(row=4, column=1, sticky=tk.W, padx=5)

        ttk.Label(frame, text="Raw:").grid(row=5, column=0, sticky=tk.W, padx=5)
        self.ht_raw = ttk.Label(frame, text="--", foreground="gray", wraplength=500)
        self.ht_raw.grid(row=5, column=1, columnspan=2, sticky=tk.W, padx=5)

        # Control buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=6, column=0, columnspan=3, pady=10)

        self.ht_manual_btn = ttk.Button(btn_frame, text="Read Once", command=self.manual_read_ht)
        self.ht_manual_btn.pack(side=tk.LEFT, padx=5)

        self.ht_auto_btn = ttk.Button(btn_frame, text="Start Auto", command=self.toggle_ht_auto)
        self.ht_auto_btn.pack(side=tk.LEFT, padx=5)

        self.ht_status = ttk.Label(btn_frame, text="Manual", foreground="gray")
        self.ht_status.pack(side=tk.LEFT, padx=5)

    def create_tilt_acc_section(self, parent):
        frame = ttk.LabelFrame(parent, text="Tilt & Acceleration", padding="10")
        frame.pack(fill=tk.X, pady=5)
        frame.columnconfigure(2, weight=1)

        # Device EUI
        ttk.Label(frame, text="Device EUI:").grid(row=0, column=0, sticky=tk.W, padx=5)
        self.ta_eui_entry = ttk.Entry(frame, width=30)
        self.ta_eui_entry.grid(row=0, column=1, columnspan=2, sticky=(tk.W, tk.E), padx=5, pady=2)
        self.ta_eui_entry.insert(0, TILT_ACC_EUI)

        # Data fields
        ttk.Label(frame, text="Roll:").grid(row=1, column=0, sticky=tk.W, padx=5)
        self.ta_roll = ttk.Label(frame, text="--", font=('Arial', 11, 'bold'))
        self.ta_roll.grid(row=1, column=1, sticky=tk.W, padx=5)

        ttk.Label(frame, text="Pitch:").grid(row=2, column=0, sticky=tk.W, padx=5)
        self.ta_pitch = ttk.Label(frame, text="--", font=('Arial', 11, 'bold'))
        self.ta_pitch.grid(row=2, column=1, sticky=tk.W, padx=5)

        ttk.Label(frame, text="Yaw:").grid(row=3, column=0, sticky=tk.W, padx=5)
        self.ta_yaw = ttk.Label(frame, text="--", font=('Arial', 11, 'bold'))
        self.ta_yaw.grid(row=3, column=1, sticky=tk.W, padx=5)

        ttk.Label(frame, text="Ax (g):").grid(row=4, column=0, sticky=tk.W, padx=5)
        self.ta_ax = ttk.Label(frame, text="--", font=('Arial', 11, 'bold'))
        self.ta_ax.grid(row=4, column=1, sticky=tk.W, padx=5)

        ttk.Label(frame, text="Ay (g):").grid(row=5, column=0, sticky=tk.W, padx=5)
        self.ta_ay = ttk.Label(frame, text="--", font=('Arial', 11, 'bold'))
        self.ta_ay.grid(row=5, column=1, sticky=tk.W, padx=5)

        ttk.Label(frame, text="Az (g):").grid(row=6, column=0, sticky=tk.W, padx=5)
        self.ta_az = ttk.Label(frame, text="--", font=('Arial', 11, 'bold'))
        self.ta_az.grid(row=6, column=1, sticky=tk.W, padx=5)

        ttk.Label(frame, text="Raw:").grid(row=7, column=0, sticky=tk.W, padx=5)
        self.ta_raw = ttk.Label(frame, text="--", foreground="gray", wraplength=500)
        self.ta_raw.grid(row=7, column=1, columnspan=2, sticky=tk.W, padx=5)

        # Control buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=8, column=0, columnspan=3, pady=10)

        self.ta_manual_btn = ttk.Button(btn_frame, text="Read Once", command=self.manual_read_ta)
        self.ta_manual_btn.pack(side=tk.LEFT, padx=5)

        self.ta_auto_btn = ttk.Button(btn_frame, text="Start Auto", command=self.toggle_ta_auto)
        self.ta_auto_btn.pack(side=tk.LEFT, padx=5)

        self.ta_status = ttk.Label(btn_frame, text="Manual", foreground="gray")
        self.ta_status.pack(side=tk.LEFT, padx=5)

    def create_water_level_section(self, parent):
        frame = ttk.LabelFrame(parent, text="Water Level", padding="10")
        frame.pack(fill=tk.X, pady=5)
        frame.columnconfigure(2, weight=1)

        # Device EUI
        ttk.Label(frame, text="Device EUI:").grid(row=0, column=0, sticky=tk.W, padx=5)
        self.wl_eui_entry = ttk.Entry(frame, width=30)
        self.wl_eui_entry.grid(row=0, column=1, columnspan=2, sticky=(tk.W, tk.E), padx=5, pady=2)
        self.wl_eui_entry.insert(0, WATER_LEVEL_EUI)

        # Data fields
        ttk.Label(frame, text="Level:").grid(row=1, column=0, sticky=tk.W, padx=5)
        self.wl_level = ttk.Label(frame, text="--", font=('Arial', 11, 'bold'))
        self.wl_level.grid(row=1, column=1, sticky=tk.W, padx=5)

        ttk.Label(frame, text="CRC:").grid(row=2, column=0, sticky=tk.W, padx=5)
        self.wl_crc = ttk.Label(frame, text="--", foreground="gray")
        self.wl_crc.grid(row=2, column=1, sticky=tk.W, padx=5)

        ttk.Label(frame, text="Raw:").grid(row=3, column=0, sticky=tk.W, padx=5)
        self.wl_raw = ttk.Label(frame, text="--", foreground="gray", wraplength=500)
        self.wl_raw.grid(row=3, column=1, columnspan=2, sticky=tk.W, padx=5)

        # Control buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=4, column=0, columnspan=3, pady=10)

        self.wl_manual_btn = ttk.Button(btn_frame, text="Read Once", command=self.manual_read_wl)
        self.wl_manual_btn.pack(side=tk.LEFT, padx=5)

        self.wl_auto_btn = ttk.Button(btn_frame, text="Start Auto", command=self.toggle_wl_auto)
        self.wl_auto_btn.pack(side=tk.LEFT, padx=5)

        self.wl_status = ttk.Label(btn_frame, text="Manual", foreground="gray")
        self.wl_status.pack(side=tk.LEFT, padx=5)

    def create_radar_section(self, parent):
        frame = ttk.LabelFrame(parent, text="mmWave Radar Targets", padding="10")
        frame.pack(fill=tk.BOTH, expand=True)

        # Device EUI for mmWave
        eui_frame = ttk.Frame(frame)
        eui_frame.pack(fill=tk.X, pady=5)
        ttk.Label(eui_frame, text="Device EUI:").pack(side=tk.LEFT, padx=5)
        self.mmwave_eui_entry = ttk.Entry(eui_frame, width=30)
        self.mmwave_eui_entry.pack(side=tk.LEFT, padx=5)
        self.mmwave_eui_entry.insert(0, MMWAVE_EUI)

        # Matplotlib figure for radar plot
        self.fig = Figure(figsize=(4.3, 4.3), dpi=100)
        self.ax = self.fig.add_subplot(111, projection='polar')
        self.setup_radar_plot()

        # Canvas
        self.canvas = FigureCanvasTkAgg(self.fig, master=frame)
        self.canvas.get_tk_widget().pack(fill=tk.NONE, expand=False)

        # Target data display
        target_frame = ttk.Frame(frame)
        target_frame.pack(fill=tk.X, pady=10)

        ttk.Label(target_frame, text="Detected Targets:", font=('Arial', 15, 'bold')).pack(anchor=tk.W)

        self.target_labels = []
        for i in range(5):
            label = ttk.Label(target_frame, text=f"Target {i+1}: --", font=('Arial', 13))
            label.pack(anchor=tk.W, padx=10, pady=2)
            self.target_labels.append(label)

        # Control buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=10)

        self.mmwave_manual_btn = ttk.Button(btn_frame, text="Read Once", command=self.manual_read_mmwave)
        self.mmwave_manual_btn.pack(side=tk.LEFT, padx=5)

        self.mmwave_auto_btn = ttk.Button(btn_frame, text="Start Auto", command=self.toggle_mmwave_auto)
        self.mmwave_auto_btn.pack(side=tk.LEFT, padx=5)

        self.mmwave_status = ttk.Label(btn_frame, text="Manual", foreground="gray")
        self.mmwave_status.pack(side=tk.LEFT, padx=5)

    def setup_radar_plot(self):
        """Setup the polar radar plot."""
        self.ax.clear()
        self.ax.set_theta_zero_location('N')
        self.ax.set_theta_direction(-1)
        self.ax.set_thetamin(-90)  # ADD THIS LINE
        self.ax.set_thetamax(90)  # ADD THIS LINE
        self.ax.set_ylim(0, 8)
        self.ax.set_title('mmWave Radar Detection', pad=20, fontsize=12, fontweight='bold')
        self.ax.grid(True, linestyle='--', alpha=0.7)

        # Add degree markers
        angles = np.deg2rad(np.arange(-90, 91, 30))
        self.ax.set_xticks(angles)
        self.ax.set_xticklabels([f'{int(np.rad2deg(a))}°' for a in angles])

    def update_radar_plot(self, targets):
        """Update radar plot with target data."""
        self.setup_radar_plot()

        # Plot targets
        for target_name, data in targets.items():
            if len(data) >= 2:
                angle_deg, distance = data[0], data[1]
                if distance > 0:  # Only plot if distance is valid
                    angle_rad = math.radians(angle_deg)
                    self.ax.plot(angle_rad, distance, 'ro', markersize=12, markeredgecolor='darkred', markeredgewidth=2)
                    self.ax.annotate(target_name, xy=(angle_rad, distance),
                                   xytext=(8, 8), textcoords='offset points',
                                   fontsize=10, color='darkred', fontweight='bold',
                                   bbox=dict(boxstyle='round,pad=0.3', facecolor='yellow', alpha=0.7))

        self.canvas.draw()

    def update_target_display(self, targets):
        """Update target data display."""
        for i, label in enumerate(self.target_labels):
            target_name = f"target{i+1}"
            if target_name in targets:
                angle, distance = targets[target_name]
                if distance > 0:
                    label.config(text=f"Target {i+1}: {angle:.1f}° @ {distance:.2f}m", foreground="black")
                else:
                    label.config(text=f"Target {i+1}: --", foreground="gray")
            else:
                label.config(text=f"Target {i+1}: --", foreground="gray")

    # ===== Auto/Manual Toggle Functions =====

    def toggle_ht_auto(self):
        self.ht_auto = not self.ht_auto
        if self.ht_auto:
            self.ht_auto_btn.config(text="Stop Auto")
            self.ht_status.config(text="Auto Running", foreground="green")
        else:
            self.ht_auto_btn.config(text="Start Auto")
            self.ht_status.config(text="Manual", foreground="gray")

    def toggle_ta_auto(self):
        self.ta_auto = not self.ta_auto
        if self.ta_auto:
            self.ta_auto_btn.config(text="Stop Auto")
            self.ta_status.config(text="Auto Running", foreground="green")
        else:
            self.ta_auto_btn.config(text="Start Auto")
            self.ta_status.config(text="Manual", foreground="gray")

    def toggle_wl_auto(self):
        self.wl_auto = not self.wl_auto
        if self.wl_auto:
            self.wl_auto_btn.config(text="Stop Auto")
            self.wl_status.config(text="Auto Running", foreground="green")
        else:
            self.wl_auto_btn.config(text="Start Auto")
            self.wl_status.config(text="Manual", foreground="gray")

    def toggle_mmwave_auto(self):
        self.mmwave_auto = not self.mmwave_auto
        if self.mmwave_auto:
            self.mmwave_auto_btn.config(text="Stop Auto")
            self.mmwave_status.config(text="Auto Running", foreground="green")
        else:
            self.mmwave_auto_btn.config(text="Start Auto")
            self.mmwave_status.config(text="Manual", foreground="gray")

    # ===== Manual Read Functions =====

    def manual_read_ht(self):
        threading.Thread(
            target=partial(self._read_and_update_once, self.ht_eui_entry, sensor_service.read_ht, self.update_ht_display),
            daemon=True
        ).start()

    def manual_read_ta(self):
        threading.Thread(
            target=partial(self._read_and_update_once, self.ta_eui_entry, sensor_service.read_ta, self.update_ta_display),
            daemon=True
        ).start()

    def manual_read_wl(self):
        threading.Thread(
            target=partial(self._read_and_update_once, self.wl_eui_entry, sensor_service.read_wl, self.update_wl_display),
            daemon=True
        ).start()

    def manual_read_mmwave(self):
        threading.Thread(target=self._read_mmwave_once, daemon=True).start()

    # ===== Auto Polling Threads =====

    def start_all_polling_threads(self):
        threading.Thread(
            target=partial(
                self._polling_loop,
                lambda: self.ht_auto,
                partial(self._read_and_update_once, self.ht_eui_entry, sensor_service.read_ht, self.update_ht_display)
            ),
            daemon=True
        ).start()
        threading.Thread(
            target=partial(
                self._polling_loop,
                lambda: self.ta_auto,
                partial(self._read_and_update_once, self.ta_eui_entry, sensor_service.read_ta, self.update_ta_display)
            ),
            daemon=True
        ).start()
        threading.Thread(
            target=partial(
                self._polling_loop,
                lambda: self.wl_auto,
                partial(self._read_and_update_once, self.wl_eui_entry, sensor_service.read_wl, self.update_wl_display)
            ),
            daemon=True
        ).start()
        threading.Thread(target=self.mmwave_polling_loop, daemon=True).start()

    def _polling_loop(self, is_auto_enabled: Callable[[], bool], read_action: Callable[[], None]):
        while True:
            if is_auto_enabled():
                read_action()
            time.sleep(self.poll_interval)

    def mmwave_polling_loop(self):
        while True:
            if self.mmwave_auto:
                self._read_mmwave_once()
            time.sleep(self.poll_interval)

    # ===== Actual Read Functions =====

    def _read_and_update_once(self, eui_entry, read_func: Callable, update_func: Callable):
        dev_eui = eui_entry.get().strip()
        try:
            result = read_func(dev_eui, timeout=20.0)

            if not result or not result.get("ok"):
                return

            data = result.get("data")
            self.root.after(0, lambda: update_func(data))
        except Exception:
            return

    def _read_mmwave_once(self):
        dev_eui = self.mmwave_eui_entry.get().strip()
        try:
            result = sensor_service.read_mmwave(dev_eui, timeout=20.0)

            if result and result.get("ok"):
                targets_dict = result.get("data", {}).get("targets", {})
                if targets_dict:
                    self.mmwave_targets = targets_dict
                    self.root.after(0, lambda: self.update_radar_plot(targets_dict))
                    self.root.after(0, lambda: self.update_target_display(targets_dict))
                else:
                    self.root.after(0, lambda: self.update_radar_plot({}))
                    self.root.after(0, lambda: self.update_target_display({}))
            else:
                self.root.after(0, lambda: self.update_radar_plot({}))
                self.root.after(0, lambda: self.update_target_display({}))
        except Exception:
            self.root.after(0, lambda: self.update_radar_plot({}))
            self.root.after(0, lambda: self.update_target_display({}))

    # ===== Display Update Functions =====

    def update_ht_display(self, data):
        self.ht_temp.config(text=f"{data['temperature_c']:.2f} °C")
        self.ht_humidity.config(text=f"{data['humidity_rh']:.2f} %RH")
        self.ht_dewpoint.config(text=f"{data['dewpoint_c']:.2f} °C")
        self.ht_crc.config(text=str(data['crc_valid']))
        self.ht_raw.config(text=data['raw_hex'])

    def update_ta_display(self, data):
        self.ta_roll.config(text=f"{data['roll']:.2f}°")
        self.ta_pitch.config(text=f"{data['pitch']:.2f}°")
        self.ta_yaw.config(text=f"{data['yaw']:.2f}°")
        self.ta_ax.config(text=f"{data['ax_g']:.3f}g")
        self.ta_ay.config(text=f"{data['ay_g']:.3f}g")
        self.ta_az.config(text=f"{data['az_g']:.3f}g")
        self.ta_raw.config(text=data['raw_hex'])

    def update_wl_display(self, data):
        self.wl_level.config(text=f"{data['level_m']:.3f} m")
        self.wl_crc.config(text=str(data['crc_valid']))
        self.wl_raw.config(text=data['raw_hex'])


def main(mode: str = "real"):
    if mode == "fake":
        os.environ["USE_FAKE_SERVER"] = "1"
    else:
        os.environ.pop("USE_FAKE_SERVER", None)

    root = tk.Tk()
    app = SensorDashboard(root)
    root.mainloop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run GUI in real or fake gateway mode")
    parser.add_argument("--mode", choices=["real", "fake"], default="real")
    args = parser.parse_args()
    main(args.mode)