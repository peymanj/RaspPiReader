import csv
import os.path
import tempfile
import webbrowser
from datetime import datetime

import google
import jinja2
import pdfkit
from PyQt5.QtCore import QTimer, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QMainWindow, QErrorMessage, QMessageBox, QApplication
from colorama import Fore

from RaspPiReader import pool
from RaspPiReader.libs.gdrive_api import GoogleDriveAPI
from RaspPiReader.ui.google_auth_form import GoogleAuthForm
from .mainForm import MainForm
from .plot_handler import InitiatePlotWidget
from .plot_preview_form_handler import PlotPreviewFormHandler
from .setting_form_handler import SettingFormHandler, CHANNEL_COUNT
from .start_cycle_form_handler import StartCycleFormHandler


def timedelta2str(td):
    h, rem = divmod(td.seconds, 3600)
    m, s = divmod(rem, 60)

    def zp(val):
        return str(val) if val >= 10 else f"0{val}"

    return "{0}:{1}:{2}".format(zp(h), zp(m), zp(s))


class MainFormHandler(QMainWindow):
    update_status_bar_signal = pyqtSignal(str, int, str)

    def __init__(self) -> object:
        super(MainFormHandler, self).__init__()
        self.form_obj = MainForm()
        self.form_obj.setupUi(self)
        self.file_name = None
        self.folder_name = None
        self.csv_path = None
        self.pdf_path = None
        pool.set('main_form', self)
        self.cycle_timer = QTimer()
        self.set_connections()
        self.start_cycle_form = pool.set('cycle_start_form', StartCycleFormHandler())
        self.showMaximized()

    def set_connections(self):
        # Actions
        self.actionExit.triggered.connect(self.close)
        self.actionCycle_Info.triggered.connect(self._show_cycle_info)
        self.actionPlot.triggered.connect(self._show_plot)
        self.actionSetting.triggered.connect(self._show_setting_form)
        self.actionStart.triggered.connect(self._start)
        self.actionStart.triggered.connect(lambda: self.actionPlot_preview.setEnabled(False))
        self.actionStop.triggered.connect(self._stop)
        self.actionSync_GDrive.triggered.connect(self._sync_gdrive)
        self.actionTest_GDrive.triggered.connect(self.test_gdrive_connection)
        self.actionPlot_preview.triggered.connect(self.show_plot_preview)
        self.actionPrint_results.triggered.connect(self.open_pdf)
        self.cycle_timer.timeout.connect(self.cycle_timer_update)
        self.update_status_bar_signal.connect(self.update_status_bar)
        # buttons

    def create_stack(self):
        # initialize data stack: [[process_time(minutes)], [v1], [v2], ... , [V14], sampling_time,]
        data_stack = []
        test_data_stack = []
        for i in range(CHANNEL_COUNT + 2):
            data_stack.append([])
            test_data_stack.append([])
            self.data_stack = pool.set("data_stack", data_stack)
            self.test_data_stack = pool.set("test_data_stack", test_data_stack)

    def load_active_channels(self):
        self.active_channels = []
        for i in range(CHANNEL_COUNT):
            if pool.config('active' + str(i + 1), bool):
                self.active_channels.append(i + 1)
        return pool.set('active_channels', self.active_channels)

    def _start(self):
        self.gdrive_csv_file_id = None
        self.gdrive_folder_id = None
        self.gdrive_pdf_file_id = None

        self.create_stack()
        self.active_channels = self.load_active_channels()
        self.initialize_ui_panels()
        self.plot = self.create_plot(plot_layout=self.plotAreaLayout, legend_layout=self.formLayoutLegend)
        self.start_cycle_form.show()

    def _stop(self):
        self.start_cycle_form.stop_cycle()
        self.actionStart.setEnabled(True)
        self.actionStop.setEnabled(False)
        self.actionSync_GDrive.setEnabled(True)
        self.actionPrint_results.setEnabled(True)
        self.show_plot_preview()
        QTimer.singleShot(1000, self.close_csv_file)


    def show_plot_preview(self):
        self.plot_preview_form = pool.set('plot_preview_form', PlotPreviewFormHandler())
        self.plot_preview_form.initiate_plot(self.headers)

    def _sync_gdrive(self, *args,  upload_csv=True, upload_pdf=True, show_message=True, delete_existing=True):
        try:
            gapi = GoogleDriveAPI()
            init_data = gapi.check_creds()
            if not self.gdrive_folder_id:
                self.gdrive_folder_id = gapi.create_folder(self.folder_name)
            if upload_pdf:
                if self.gdrive_pdf_file_id and delete_existing:
                    gapi.delete_file(self.gdrive_pdf_file_id)
                    self.gdrive_pdf_file_id = None

                if not self.gdrive_pdf_file_id:
                    self.gdrive_pdf_file_id = gapi.upload_file(self.folder_name, 'application/pdf', self.pdf_path,
                                                               self.gdrive_folder_id)
                    print(Fore.GREEN + "Google drive PDF upload successful: {}".format(datetime.now()))
                else:
                    gapi.update_file(self.gdrive_pdf_file_id, self.pdf_path)
                    print(Fore.GREEN + "Google drive PDF update successful: {}".format(datetime.now()))

            if upload_csv:
                if self.gdrive_csv_file_id and delete_existing:
                    gapi.delete_file(self.gdrive_csv_file_id)
                    self.gdrive_csv_file_id = None

                if not self.gdrive_csv_file_id:
                    self.gdrive_csv_file_id = gapi.upload_file(self.folder_name, 'text/csv', self.csv_path,
                                                               self.gdrive_folder_id)
                    msg = "Google drive CSV upload successful: {}. ".format(datetime.now().strftime("%H:%M:%S"))
                else:
                    gapi.update_file(self.gdrive_csv_file_id, self.csv_path)
                    msg = "Google drive CSV update successful: {}. ".format(datetime.now().strftime("%H:%M:%S"))
                print(Fore.GREEN + msg)
                self.update_status_bar_signal.emit(msg, 10000, 'green')

            if show_message:
                msg = QMessageBox()
                msg.setIcon(QMessageBox.Information)
                msg.setText("Upload successful.")
                msg.setStandardButtons(QMessageBox.Ok)
                msg.exec_()

        except Exception as e:
            if show_message:
                msg = QMessageBox()
                msg.setIcon(QMessageBox.Critical)
                msg.setText("Upload Failed.\n" + str(e))
                msg.setStandardButtons(QMessageBox.Ok)
                msg.exec_()
            else:
                msg = "Google drive update/upload failed: {}. \n".format(datetime.now().strftime("%H:%M:%S")) + str(e)
                print(Fore.RED + msg)
                self.update_status_bar_signal.emit(msg, 0, 'red')

    def test_gdrive_connection(self):
        msg = QMessageBox()
        try:
            gapi = GoogleDriveAPI()
            init_data = gapi.check_creds()
            if init_data == FileNotFoundError:
                self.get_gdrive_auth_file()
                return
            gapi.check_connection()
            msg.setIcon(QMessageBox.Information)
            msg.setText("Connection OK.")
            msg.setStandardButtons(QMessageBox.Ok)
            msg.exec_()
            self.update_status_bar_signal.emit('Google drive connection OK.', 15000, 'green')

        except google.auth.exceptions.RefreshError as e:
            msg.setIcon(QMessageBox.Critical)
            msg.setText("Connection failed.\n" + str(e))
            msg.setStandardButtons(QMessageBox.Ok)
            msg.exec_()
            self.get_gdrive_auth_file()
            self.update_status_bar_signal.emit('Google drive connection failed.', 0, 'red')
            return

        except Exception as e:
            msg.setIcon(QMessageBox.Critical)
            msg.setText("Connection failed.\n" + str(e))
            msg.setStandardButtons(QMessageBox.Ok)
            msg.exec_()
            self.update_status_bar_signal.emit('Google drive connection failed.', 0, 'red')

    def get_gdrive_auth_file(self):
        self.creds_input_form = GoogleAuthForm()
        self.creds_input_form.setupUi(self)
        self.creds_input_form.show()

    def _print_result(self):
        pass

    def _show_cycle_info(self, checked):
        self.cycle_infoGroupBox.setVisible(checked)

    def _show_plot(self, checked):
        self.mainPlotGroupBox.setVisible(checked)

    def _save(self):
        pass

    def _save_as(self):
        pass

    def _show_setting_form(self):
        self.setting_form = SettingFormHandler()

    def _exit(self):
        pass

    def create_plot(self, plot_layout=None, legend_layout=None):

        self.plot_update_locked = False
        self.headers = list()
        self.headers.append(pool.config('h_label'))
        self.headers.append(pool.config('left_v_label'))
        self.headers.append(pool.config('right_v_label'))
        for i in range(1, CHANNEL_COUNT + 1):
            self.headers.append(pool.config('label' + str(i)))

        # Clear old plot if exists
        if plot_layout is not None:
            for i in reversed(range(plot_layout.count())):
                plot_layout.itemAt(i).widget().setParent(None)
        if legend_layout is not None:
            for i in reversed(range(legend_layout.count())):
                legend_layout.itemAt(i).widget().setParent(None)

        return InitiatePlotWidget(pool.get('active_channels'), plot_layout, legend_layout=legend_layout,
                                  headers=self.headers)

    def update_plot(self):
        if self.plot_update_locked:
            return
        self.plot_update_locked = True
        self.plot.update_plot()
        self.plot_update_locked = False

    def initialize_ui_panels(self):
        self.immediate_panel_update_locked = False
        active_channels = pool.get('active_channels')
        for i in range(CHANNEL_COUNT):

            getattr(self, 'chLabel' + str(i + 1)).setText(pool.config('label' + str(i + 1)))
            spin_widget = getattr(self, 'ch' + str(i + 1) + 'Value')
            if (i + 1) not in self.active_channels:
                spin_widget.setEnabled(False)
            else:
                spin_widget.setEnabled(True)
                spin_widget.setDecimals(pool.config('decimal_point' + str(i + 1), int))
                spin_widget.setMinimum(-999999)
                spin_widget.setMaximum(+999999)

    def update_data(self):
        self.update_csv_file()
        QApplication.processEvents()
        self.update_immediate_values_panel()
        # QApplication.processEvents()
        self.update_plot()
        # QApplication.processEvents()

    def update_immediate_test_values_panel(self):
        for i in self.active_channels:
            spin_widget = getattr(self, 'ch' + str(i) + 'Value')
            if self.test_data_stack[i]:
                spin_widget.setValue(self.test_data_stack[i][-1])
            self.test_data_stack[i] = []

    def update_immediate_values_panel(self):
        if self.immediate_panel_update_locked:
            return
        self.immediate_panel_update_locked = True
        for i in range(CHANNEL_COUNT):
            spin_widget = getattr(self, 'ch' + str(i + 1) + 'Value')
            spin_widget.setValue(self.data_stack[i + 1][-1])
            self.o1.setText(str(self.start_cycle_form.core_temp_above_setpoint_time or 'N/A'))
            self.o2.setText(str(self.start_cycle_form.pressure_drop_core_temp or 'N/A'))
        self.immediate_panel_update_locked = False

    def cycle_timer_update(self):
        self.run_duration.setText(timedelta2str(datetime.now() - self.start_cycle_form.cycle_start_time))
        self.d6.setText(datetime.now().strftime("%H:%M:%S"))  # Cycle end time

    def update_cycle_info_pannel(self):
        self.d1.setText(pool.config("cycle_id"))
        self.d2.setText(pool.config("order_id"))
        self.d3.setText(pool.config("quantity"))
        self.d4.setText(self.start_cycle_form.cycle_start_time.strftime("%Y/%m/%d"))
        self.d5.setText(self.start_cycle_form.cycle_start_time.strftime("%H:%M:%S"))
        self.d7.setText(pool.config("cycle_location"))
        self.p1.setText(pool.config("maintain_vacuum"))
        self.p2.setText(pool.config("initial_set_cure_temp"))
        self.p3.setText(pool.config("temp_ramp"))
        self.p4.setText(pool.config("set_pressure"))
        self.p5.setText(pool.config("dwell_time"))
        self.p6.setText(pool.config("cool_down_temp"))
        self.cH1Label_36.setText(f"TIME (min) CORE TEMP ≥ {pool.config('core_temp_setpoint')} °C:")

    def create_csv_file(self):
        self.csv_update_locked = False
        self.last_written_index = 0
        file_extension = '.csv'
        csv_full_path = os.path.join(self.start_cycle_form.folder_path,
                                     self.start_cycle_form.file_name + file_extension)
        self.csv_path = csv_full_path
        delimiter = pool.config('csv_delimiter') or ' '
        csv.register_dialect('unixpwd', delimiter=delimiter)
        self.open_csv_file(mode='w')
        self.write_cycle_info_to_csv()

    def open_csv_file(self, mode='a'):
        self.csv_file = open(self.csv_path, mode, newline='')
        self.csv_writer = csv.writer(self.csv_file)

    def close_csv_file(self):
        self.csv_file.close()

    def write_cycle_info_to_csv(self):
        data = [
            ["Work Order", pool.config("order_id")],
            ["Cycle Number", pool.config("cycle_id")],
            ["Quantity", pool.config("quantity")],
            ["Process Start Time", self.start_cycle_form.cycle_start_time],
        ]
        self.csv_writer.writerows(data)
        self.csv_writer.writerows([['Date', 'Time', 'Timer(min)'] + self.headers[3:]])

    def update_csv_file(self):
        if self.csv_update_locked:
            return
        self.csv_update_locked = True
        n_data = len(self.data_stack[0])
        temp_data = []

        for i in range(self.last_written_index, n_data):
            temp_rec = []
            temp_rec.append(self.data_stack[15][i].strftime("%Y/%m/%d"))
            temp_rec.append(self.data_stack[15][i].strftime("%H:%M:%S"))
            temp_rec.append(self.data_stack[0][i])
            for j in range(CHANNEL_COUNT):
                temp_rec.append(self.data_stack[j + 1][i])
            temp_data.append(temp_rec)
        self.csv_writer.writerows(temp_data)
        self.last_written_index = n_data
        self.csv_file.flush()
        self.csv_update_locked = False

    def show_error_and_stop(self, msg, parent=None):
        error_dialog = QErrorMessage(parent or self)
        error_dialog.showMessage(msg)
        self.start_cycle_form.stop_cycle()
        self.actionStart.setEnabled(True)
        self.actionStop.setEnabled(False)
        self.csv_file.close()

    def generate_html_report(self, image_path=None):
        report_data = {
            "order_id": pool.config("order_id") or "-",
            "cycle_id": pool.config("cycle_id") or "-",
            "quantity": pool.config("quantity") or "-",
            "cycle_location": pool.config("cycle_location") or "-",
            "dwell_time": int(pool.config("dwell_time")) or "-",
            "cool_down_temp": pool.config("cool_down_temp") or "-",
            "core_temp_setpoint": pool.config("core_temp_setpoint") or "-",
            "temp_ramp": pool.config("temp_ramp") or "-",
            "set_pressure": pool.config("set_pressure") or "-",
            "maintain_vacuum": pool.config("maintain_vacuum") or "-",
            "initial_set_cure_temp": pool.config("initial_set_cure_temp") or "-",
            "final_set_cure_temp": pool.config("final_set_cure_temp") or "-",
            "core_high_temp_time": round(self.start_cycle_form.core_temp_above_setpoint_time, 2) or "-",
            "release_temp": self.start_cycle_form.pressure_drop_core_temp or "-",
            "cycle_date": self.start_cycle_form.cycle_start_time.strftime("%Y/%m/%d") or "-",
            "cycle_start_time": self.start_cycle_form.cycle_start_time.strftime("%H:%M:%S") or "-",
            "cycle_end_time": self.start_cycle_form.cycle_end_time.strftime("%H:%M:%S") or "-",
            "image_path": image_path,
            "logo_path": os.path.join(os.getcwd(), 'ui\\logo.jpg'),
        }

        self.render_print_template(template_file='result_template.html',
                                   data=report_data,
                                   )

    def render_print_template(self, *args, template_file=None, **kwargs):
        templateLoader = jinja2.FileSystemLoader(searchpath=
                                                 os.path.join(os.getcwd(), "ui"))
        templateEnv = jinja2.Environment(loader=templateLoader, extensions=['jinja2.ext.loopcontrols'])
        template = templateEnv.get_template(template_file)
        html = template.render(**kwargs)
        with tempfile.NamedTemporaryFile('w', delete=False, suffix='.html') as f:
            fname = f.name
            f.write(html)
        # webbrowser.open('file://' + fname)
        file_extension = '.pdf'
        pdf_full_path = os.path.join(self.start_cycle_form.folder_path,
                                     self.start_cycle_form.file_name + file_extension)
        self.html2pdf(fname, pdf_full_path)

    def html2pdf(self, html_path, pdf_path):
        self.pdf_path = pdf_path
        """
        Convert html to pdf using pdfkit which is a wrapper of wkhtmltopdf
        """
        options = {
            'page-size': 'A4',
            'dpi': 2000,
            'margin-top': '0.35in',
            'margin-right': '0.75in',
            'margin-bottom': '0.75in',
            'margin-left': '0.75in',
            'encoding': "UTF-8",
            'no-outline': None,
            'enable-local-file-access': None
        }
        path_wkhtmltopdf = os.path.join(os.getcwd(), 'wkhtmltopdf.exe')
        print(html_path)
        print(pdf_path)
        print('exe: ', path_wkhtmltopdf)
        config = pdfkit.configuration(wkhtmltopdf=path_wkhtmltopdf)
        with open(html_path) as f:
            pdfkit.from_file(f, pdf_path, options=options, configuration=config)
        webbrowser.open('file://' + pdf_path)

    def open_pdf(self):
        webbrowser.open('file://' + self.pdf_path)

    def closeEvent(self, event):
        if hasattr(self, 'start_cycle_form') \
                and hasattr(self.start_cycle_form, 'running') \
                and self.start_cycle_form.running:
            quit_msg = "Are you Sure?\nCSV data may be not be saved."
        else:
            quit_msg = "Are you sure?"
        reply = QMessageBox.question(self, 'Exiting app ...',
                                     quit_msg, (QMessageBox.Yes | QMessageBox.Cancel))
        if reply == QMessageBox.Yes:
            event.accept()

        elif reply == QMessageBox.Cancel:
            event.ignore()
        # super().closeEvent(event)

    def update_status_bar(self, msg, ms_timeout, color):
        self.statusbar.showMessage(msg, ms_timeout)
        self.statusbar.setStyleSheet("color: {}".format(color.lower()))
        self.statusBar().setFont(QFont('Times', 12))