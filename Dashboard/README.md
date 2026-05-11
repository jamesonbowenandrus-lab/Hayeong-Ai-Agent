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

The dashboard reads from Brain\state\core.json and Logs\ — it does not
write to them. It is read-only. Changes to the dashboard do not affect
Hayeong's operation.
