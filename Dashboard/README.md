# Dashboard\

The web dashboard for monitoring Hayeong's state.

## What Lives Here

The dashboard is a separate web application that reads from Hayeong's
shared state and logs to display her current status, active tasks,
recent conversations, and system health.

## How To Start

Run `launch_dashboard.bat` inside this folder.
The dashboard does not need to be running for Hayeong to function.
It is a monitoring tool, not a dependency.

## What To Know

The dashboard is a pure external observer. It reads from Brain\state\core.json
and Logs\ but never writes to either. Hayeong's reasoning, memory, and tool
execution are entirely unaffected by whether the dashboard is running.
If the dashboard crashes or is closed, nothing downstream breaks.
