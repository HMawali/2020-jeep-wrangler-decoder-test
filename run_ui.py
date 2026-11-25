#!/usr/bin/env python3
"""
run_ui.py - one-command launcher for the Tazer JL Cockpit desktop UI.

    python run_ui.py                (or double-click run_ui.bat on Windows)

Pure standard library: no pip install, no npm, no build step. Starts a tiny local HTTP
bridge that reuses the real tazer_config backend and opens the cockpit in your browser.
Works fully in SIMULATOR mode with nothing plugged in; switch to LIVE TRUCK in the top bar
when the WeAct USB2CANFD + SGW bypass are connected.
"""
import os
import sys
import runpy

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, 'tazer_config', 'ui', 'server.py')

if __name__ == '__main__':
    if not os.path.exists(SERVER):
        sys.exit('cannot find %s' % SERVER)
    # allow `python run_ui.py 8900` to pick a port
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        os.environ['TAZER_UI_PORT'] = sys.argv[1]
    sys.argv = [SERVER]
    runpy.run_path(SERVER, run_name='__main__')
