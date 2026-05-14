# Toolbox/email

Email reading and sending for Hayeong.

## Files

- `email_bridge.py` — main tool, `run()` function, registered in `registry.json`
- `email_monitor.py` — background email monitoring

## Calling This Tool

    action: email
    params: action=read

    action: email
    params: action=send, to=address@example.com, subject=Subject, body=Message body

## Configuration

Email credentials are set in `Brain/config.py`:

    EMAIL_ADDRESS  = ""
    EMAIL_PASSWORD = ""
