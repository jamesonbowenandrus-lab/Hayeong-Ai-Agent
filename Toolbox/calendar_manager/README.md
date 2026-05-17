# Toolbox/calendar_manager

Temporal awareness and planning for Hayeong.
Tracks events, schedules her own tasks, manages reminders.

## Calling This Tool

    action: calendar_manager
    params: operation=add, title=Check Etsy trends, date=tomorrow, type=hayeong_task

    action: calendar_manager
    params: operation=list, days=7

    action: calendar_manager
    params: operation=check_due

## Event Types

- james_event — things in James's schedule
- hayeong_task — things Hayeong has scheduled herself
- reminder — time-based reminders
- deadline — hard deadlines

## Natural Language Dates

today, tomorrow, in 3 days, next Thursday, end of week

## Plugin

plugin.py injects today's date and upcoming events into shared state every tick.