"""
Multi-sensor dashboard that only enqueues requests and renders buffered results.
"""

import argparse
import math
import time
import tkinter as tk
from tkinter import ttk

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import numpy as np

import communicator


# Default device IDs used to prefill the dashboard.
HUMIDITY_TEMP_EUI = "8695311000942380"
TILT_ACC_EUI = "8695311000942380"
WATER_LEVEL_EUI = "8695311000942380"
MMWAVE_EUI = "8695311001412450"


class SensorDashboard:
    def __init__(self, root):
        # Main window setup and top-level layout containers.
        self.root = root
        self.root.title("Multi-Sensor Dashboard with Radar")
        self.root.geometry("1000x750")

        style = ttk.Style()
        style.theme_use("clam")

        self.refresh_interval_ms = 1000
        self.auto_poll_interval_ms = 5000
        self.auto_enabled = {
            "ht": False,
            "ta": False,
            "wl": False,
            "mmwave": False,
        }
        self.read_started_at = {
            "ht": 0.0,
            "ta": 0.0,
            "wl": 0.0,
            "mmwave": 0.0,
        }

        main_container = ttk.Frame(root)
        main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        left_panel = ttk.Frame(main_container, width=700)
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(0, 10))

        right_panel = ttk.Frame(main_container)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self.create_humidity_temp_section(left_panel)
        self.create_tilt_acc_section(left_panel)
        self.create_water_level_section(left_panel)
        self.create_radar_section(right_panel)

        self.refresh_ui()

    def create_humidity_temp_section(self, parent):
        # Humidity/temperature card with one-shot request controls.
        frame = ttk.LabelFrame(parent, text="Humidity & Temperature", padding="10")
        frame.pack(fill=tk.X, pady=5)
        frame.columnconfigure(2, weight=1)

        ttk.Label(frame, text="Device EUI:").grid(row=0, column=0, sticky=tk.W, padx=5)
        self.ht_eui_entry = ttk.Entry(frame, width=30)
        self.ht_eui_entry.grid(row=0, column=1, columnspan=2, sticky=(tk.W, tk.E), padx=5, pady=2)
        self.ht_eui_entry.insert(0, HUMIDITY_TEMP_EUI)

        ttk.Label(frame, text="Temperature:").grid(row=1, column=0, sticky=tk.W, padx=5)
        self.ht_temp = ttk.Label(frame, text="--", font=("Arial", 11, "bold"))
        self.ht_temp.grid(row=1, column=1, sticky=tk.W, padx=5)

        ttk.Label(frame, text="Humidity:").grid(row=2, column=0, sticky=tk.W, padx=5)
        self.ht_humidity = ttk.Label(frame, text="--", font=("Arial", 11, "bold"))
        self.ht_humidity.grid(row=2, column=1, sticky=tk.W, padx=5)

        ttk.Label(frame, text="Dewpoint:").grid(row=3, column=0, sticky=tk.W, padx=5)
        self.ht_dewpoint = ttk.Label(frame, text="--", font=("Arial", 11, "bold"))
        self.ht_dewpoint.grid(row=3, column=1, sticky=tk.W, padx=5)

        ttk.Label(frame, text="CRC:").grid(row=4, column=0, sticky=tk.W, padx=5)
        self.ht_crc = ttk.Label(frame, text="--", foreground="gray")
        self.ht_crc.grid(row=4, column=1, sticky=tk.W, padx=5)

        ttk.Label(frame, text="Raw:").grid(row=5, column=0, sticky=tk.W, padx=5)
        self.ht_raw = ttk.Label(frame, text="--", foreground="gray", wraplength=500)
        self.ht_raw.grid(row=5, column=1, columnspan=2, sticky=tk.W, padx=5)

        button_row = ttk.Frame(frame)
        button_row.grid(row=6, column=0, columnspan=3, pady=10)

        ttk.Button(
            button_row,
            text="Read Once",
            command=lambda: self.enqueue_request("ht", self.ht_eui_entry),
        ).pack(side=tk.LEFT, padx=(0, 8))
        self.ht_auto_button = ttk.Button(
            button_row,
            text="Start Auto",
            command=lambda: self.toggle_auto("ht", self.ht_eui_entry, self.ht_auto_button),
        )
        self.ht_auto_button.pack(side=tk.LEFT)

        self.ht_status = ttk.Label(frame, text="", foreground="black")
        self.ht_status.grid(row=7, column=0, columnspan=3, sticky=tk.W, padx=5)

    def create_tilt_acc_section(self, parent):
        # Tilt and acceleration card for IMU readings.
        frame = ttk.LabelFrame(parent, text="Tilt & Acceleration", padding="10")
        frame.pack(fill=tk.X, pady=5)
        frame.columnconfigure(2, weight=1)

        ttk.Label(frame, text="Device EUI:").grid(row=0, column=0, sticky=tk.W, padx=5)
        self.ta_eui_entry = ttk.Entry(frame, width=30)
        self.ta_eui_entry.grid(row=0, column=1, columnspan=2, sticky=(tk.W, tk.E), padx=5, pady=2)
        self.ta_eui_entry.insert(0, TILT_ACC_EUI)

        ttk.Label(frame, text="Roll:").grid(row=1, column=0, sticky=tk.W, padx=5)
        self.ta_roll = ttk.Label(frame, text="--", font=("Arial", 11, "bold"))
        self.ta_roll.grid(row=1, column=1, sticky=tk.W, padx=5)

        ttk.Label(frame, text="Pitch:").grid(row=2, column=0, sticky=tk.W, padx=5)
        self.ta_pitch = ttk.Label(frame, text="--", font=("Arial", 11, "bold"))
        self.ta_pitch.grid(row=2, column=1, sticky=tk.W, padx=5)

        ttk.Label(frame, text="Yaw:").grid(row=3, column=0, sticky=tk.W, padx=5)
        self.ta_yaw = ttk.Label(frame, text="--", font=("Arial", 11, "bold"))
        self.ta_yaw.grid(row=3, column=1, sticky=tk.W, padx=5)

        ttk.Label(frame, text="Ax (g):").grid(row=4, column=0, sticky=tk.W, padx=5)
        self.ta_ax = ttk.Label(frame, text="--", font=("Arial", 11, "bold"))
        self.ta_ax.grid(row=4, column=1, sticky=tk.W, padx=5)

        ttk.Label(frame, text="Ay (g):").grid(row=5, column=0, sticky=tk.W, padx=5)
        self.ta_ay = ttk.Label(frame, text="--", font=("Arial", 11, "bold"))
        self.ta_ay.grid(row=5, column=1, sticky=tk.W, padx=5)

        ttk.Label(frame, text="Az (g):").grid(row=6, column=0, sticky=tk.W, padx=5)
        self.ta_az = ttk.Label(frame, text="--", font=("Arial", 11, "bold"))
        self.ta_az.grid(row=6, column=1, sticky=tk.W, padx=5)

        ttk.Label(frame, text="CRC:").grid(row=7, column=0, sticky=tk.W, padx=5)
        self.ta_crc = ttk.Label(frame, text="--", foreground="gray")
        self.ta_crc.grid(row=7, column=1, sticky=tk.W, padx=5)

        ttk.Label(frame, text="Raw:").grid(row=8, column=0, sticky=tk.W, padx=5)
        self.ta_raw = ttk.Label(frame, text="--", foreground="gray", wraplength=500)
        self.ta_raw.grid(row=8, column=1, columnspan=2, sticky=tk.W, padx=5)

        button_row = ttk.Frame(frame)
        button_row.grid(row=9, column=0, columnspan=3, pady=10)

        ttk.Button(
            button_row,
            text="Read Once",
            command=lambda: self.enqueue_request("ta", self.ta_eui_entry),
        ).pack(side=tk.LEFT, padx=(0, 8))
        self.ta_auto_button = ttk.Button(
            button_row,
            text="Start Auto",
            command=lambda: self.toggle_auto("ta", self.ta_eui_entry, self.ta_auto_button),
        )
        self.ta_auto_button.pack(side=tk.LEFT)

        self.ta_status = ttk.Label(frame, text="", foreground="black")
        self.ta_status.grid(row=10, column=0, columnspan=3, sticky=tk.W, padx=5)

    def create_water_level_section(self, parent):
        # Water level card with decoded level and raw frame display.
        frame = ttk.LabelFrame(parent, text="Water Level", padding="10")
        frame.pack(fill=tk.X, pady=5)
        frame.columnconfigure(2, weight=1)

        ttk.Label(frame, text="Device EUI:").grid(row=0, column=0, sticky=tk.W, padx=5)
        self.wl_eui_entry = ttk.Entry(frame, width=30)
        self.wl_eui_entry.grid(row=0, column=1, columnspan=2, sticky=(tk.W, tk.E), padx=5, pady=2)
        self.wl_eui_entry.insert(0, WATER_LEVEL_EUI)

        ttk.Label(frame, text="Level:").grid(row=1, column=0, sticky=tk.W, padx=5)
        self.wl_level = ttk.Label(frame, text="--", font=("Arial", 11, "bold"))
        self.wl_level.grid(row=1, column=1, sticky=tk.W, padx=5)

        ttk.Label(frame, text="CRC:").grid(row=2, column=0, sticky=tk.W, padx=5)
        self.wl_crc = ttk.Label(frame, text="--", foreground="gray")
        self.wl_crc.grid(row=2, column=1, sticky=tk.W, padx=5)

        ttk.Label(frame, text="Raw:").grid(row=3, column=0, sticky=tk.W, padx=5)
        self.wl_raw = ttk.Label(frame, text="--", foreground="gray", wraplength=500)
        self.wl_raw.grid(row=3, column=1, columnspan=2, sticky=tk.W, padx=5)

        button_row = ttk.Frame(frame)
        button_row.grid(row=4, column=0, columnspan=3, pady=10)

        ttk.Button(
            button_row,
            text="Read Once",
            command=lambda: self.enqueue_request("wl", self.wl_eui_entry),
        ).pack(side=tk.LEFT, padx=(0, 8))
        self.wl_auto_button = ttk.Button(
            button_row,
            text="Start Auto",
            command=lambda: self.toggle_auto("wl", self.wl_eui_entry, self.wl_auto_button),
        )
        self.wl_auto_button.pack(side=tk.LEFT)

        self.wl_status = ttk.Label(frame, text="", foreground="black")
        self.wl_status.grid(row=5, column=0, columnspan=3, sticky=tk.W, padx=5)

    def create_radar_section(self, parent):
        # Radar card combines polar plot and a compact target list.
        frame = ttk.LabelFrame(parent, text="mmWave Radar Targets", padding="10")
        frame.pack(fill=tk.BOTH, expand=True)

        eui_frame = ttk.Frame(frame)
        eui_frame.pack(fill=tk.X, pady=5)
        ttk.Label(eui_frame, text="Device EUI:").pack(side=tk.LEFT, padx=5)
        self.mmwave_eui_entry = ttk.Entry(eui_frame, width=30)
        self.mmwave_eui_entry.pack(side=tk.LEFT, padx=5)
        self.mmwave_eui_entry.insert(0, MMWAVE_EUI)

        self.fig = Figure(figsize=(4.3, 4.3), dpi=100)
        self.ax = self.fig.add_subplot(111, projection="polar")
        self.setup_radar_plot()

        self.canvas = FigureCanvasTkAgg(self.fig, master=frame)
        self.canvas.get_tk_widget().pack(fill=tk.NONE, expand=False)

        target_frame = ttk.Frame(frame)
        target_frame.pack(fill=tk.X, pady=10)

        ttk.Label(target_frame, text="Detected Targets:", font=("Arial", 15, "bold")).pack(anchor=tk.W)

        self.target_labels = []
        for i in range(5):
            label = ttk.Label(target_frame, text=f"Target {i + 1}: --", font=("Arial", 13))
            label.pack(anchor=tk.W, padx=10, pady=2)
            self.target_labels.append(label)

        button_row = ttk.Frame(frame)
        button_row.pack(pady=10)

        ttk.Button(
            button_row,
            text="Read Once",
            command=lambda: self.enqueue_request("mmwave", self.mmwave_eui_entry),
        ).pack(side=tk.LEFT, padx=(0, 8))
        self.mmwave_auto_button = ttk.Button(
            button_row,
            text="Start Auto",
            command=lambda: self.toggle_auto("mmwave", self.mmwave_eui_entry, self.mmwave_auto_button),
        )
        self.mmwave_auto_button.pack(side=tk.LEFT)

        self.mmwave_status = ttk.Label(frame, text="", foreground="black")
        self.mmwave_status.pack(anchor=tk.W, padx=5)

    def setup_radar_plot(self):
        # Reset plot styling before drawing the latest targets.
        self.ax.clear()
        self.ax.set_theta_zero_location("N")
        self.ax.set_theta_direction(-1)
        self.ax.set_thetamin(-90)
        self.ax.set_thetamax(90)
        self.ax.set_ylim(0, 8)
        self.ax.set_title("mmWave Radar Detection", pad=20, fontsize=12, fontweight="bold")
        self.ax.grid(True, linestyle="--", alpha=0.7)

        angles = np.deg2rad(np.arange(-90, 91, 30))
        self.ax.set_xticks(angles)
        self.ax.set_xticklabels([f"{int(np.rad2deg(a))}°" for a in angles])




### Queue sensor reads and refresh the dashboard with buffered results.
    def enqueue_request(self, sensor, eui_entry):
        # Push a read request into the communicator without blocking the UI.
        dev_eui = eui_entry.get().strip()
        if dev_eui:
            self.read_started_at[sensor] = time.time()
            self._set_status(sensor, f"{sensor} Reading...")
            communicator.enqueue_request(dev_eui, sensor)

    def toggle_auto(self, sensor, eui_entry, button):
        # Toggle periodic read requests for one sensor panel.
        self.auto_enabled[sensor] = not self.auto_enabled[sensor]
        button.config(text="Stop Auto" if self.auto_enabled[sensor] else "Start Auto")
        if self.auto_enabled[sensor]:
            self._auto_poll(sensor, eui_entry, button)

    def _auto_poll(self, sensor, eui_entry, button):
        # Re-enqueue reads until this panel's auto mode is turned off.
        if not self.auto_enabled.get(sensor):
            button.config(text="Start Auto")
            return
        self.enqueue_request(sensor, eui_entry)
        self.root.after(self.auto_poll_interval_ms, lambda: self._auto_poll(sensor, eui_entry, button))

    def refresh_ui(self):
        # Poll the shared result buffer and refresh every sensor panel.
        self._refresh_sensor(self.ht_eui_entry.get().strip(), "ht", self.update_ht_display)
        self._refresh_sensor(self.ta_eui_entry.get().strip(), "ta", self.update_ta_display)
        self._refresh_sensor(self.wl_eui_entry.get().strip(), "wl", self.update_wl_display)
        self._refresh_sensor(self.mmwave_eui_entry.get().strip(), "mmwave", self.update_mmwave_display)
        self.root.after(self.refresh_interval_ms, self.refresh_ui)

    def _refresh_sensor(self, dev_eui, sensor, update_func):
        # Read the latest buffered result for one sensor and hand it to its updater.
        if not dev_eui:
            return
        result = communicator.get_buffer_data(dev_eui, sensor)
        if not result:
            return
        if result.get("timestamp", 0) < self.read_started_at.get(sensor, 0):
            return
        if not result.get("ok"):
            self._set_status(sensor, f"{sensor} failed")
            if sensor == "mmwave":
                update_func({})
            return
        self._set_status(sensor, f"{sensor} succeeded")
        update_func(result.get("data") or {})

    def _set_status(self, sensor, text):
        color = "black"
        if "failed" in text:
            color = "red"
        elif "succeeded" in text:
            color = "green"

        if sensor == "ht":
            self.ht_status.config(text=text, foreground=color)
        elif sensor == "ta":
            self.ta_status.config(text=text, foreground=color)
        elif sensor == "wl":
            self.wl_status.config(text=text, foreground=color)
        elif sensor == "mmwave":
            self.mmwave_status.config(text=text, foreground=color)




### Update each sensor panel with the latest decoded data.
    def update_ht_display(self, data):
        # Apply decoded humidity/temperature values to the UI.
        self.ht_temp.config(text=f"{data.get('temperature_c', 0.0):.2f} °C")
        self.ht_humidity.config(text=f"{data.get('humidity_rh', 0.0):.2f} %RH")
        self.ht_dewpoint.config(text=f"{data.get('dewpoint_c', 0.0):.2f} °C")
        self.ht_crc.config(text=str(data.get("crc_valid", "--")))
        self.ht_raw.config(text=data.get("raw_hex", "--"))

    def update_ta_display(self, data):
        # Apply decoded tilt and acceleration values to the UI.
        self.ta_roll.config(text=f"{data.get('roll', 0.0):.2f}°")
        self.ta_pitch.config(text=f"{data.get('pitch', 0.0):.2f}°")
        self.ta_yaw.config(text=f"{data.get('yaw', 0.0):.2f}°")
        self.ta_ax.config(text=f"{data.get('ax_g', 0.0):.3f}g")
        self.ta_ay.config(text=f"{data.get('ay_g', 0.0):.3f}g")
        self.ta_az.config(text=f"{data.get('az_g', 0.0):.3f}g")
        self.ta_crc.config(text=str(data.get("crc_valid", "--")))
        self.ta_raw.config(text=data.get("raw_hex", "--"))

    def update_wl_display(self, data):
        # Apply decoded water level values to the UI.
        self.wl_level.config(text=f"{data.get('level_m', 0.0):.3f} m")
        self.wl_crc.config(text=str(data.get("crc_valid", "--")))
        self.wl_raw.config(text=data.get("raw_hex", "--"))

    def update_mmwave_display(self, data):
        # Update both radar visualization layers from one payload.
        targets = data.get("targets", {}) if isinstance(data, dict) else {}
        self.update_radar_plot(targets)
        self.update_target_display(targets)

    def update_radar_plot(self, targets):
        # Render detected targets on the polar radar chart.
        self.setup_radar_plot()
        for target_name, data in targets.items():
            if len(data) >= 2:
                angle_deg, distance = data[0], data[1]
                if distance > 0:
                    angle_rad = math.radians(angle_deg)
                    self.ax.plot(angle_rad, distance, "ro", markersize=12, markeredgecolor="darkred", markeredgewidth=2)
                    self.ax.annotate(
                        target_name,
                        xy=(angle_rad, distance),
                        xytext=(8, 8),
                        textcoords="offset points",
                        fontsize=10,
                        color="darkred",
                        fontweight="bold",
                        bbox=dict(boxstyle="round,pad=0.3", facecolor="yellow", alpha=0.7),
                    )
        self.canvas.draw()

    def update_target_display(self, targets):
        # Mirror radar targets in a text list for quick reading.
        for i, label in enumerate(self.target_labels):
            target_name = f"target{i + 1}"
            if target_name in targets:
                angle, distance = targets[target_name]
                if distance > 0:
                    label.config(text=f"Target {i + 1}: {angle:.1f}° @ {distance:.2f}m", foreground="black")
                    continue
            label.config(text=f"Target {i + 1}: --", foreground="gray")




def main(mode: str = "real"):
    # Configure backend mode before the UI starts issuing requests.
    communicator.configure_backend(mode)
    root = tk.Tk()
    SensorDashboard(root)
    root.mainloop()


if __name__ == "__main__":
    # CLI entry point for launching the dashboard against real or fake backend.
    parser = argparse.ArgumentParser(description="Run GUI in real or fake gateway mode")
    parser.add_argument("--mode", choices=["real", "fake"], default="real")
    args = parser.parse_args()
    main(args.mode)
