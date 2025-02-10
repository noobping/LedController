# LedController
The docker-based LedController for LS HQ

## Web API

| Method | Path | Description |
| --- | --- | --- |
| GET | /health | Check if the WLEDs are reachable | 
| GET | /videolist | Get a list of all available videos |

## Vidio player

Install the dependencies
```bash
pip install keyboard
```

Run the video player
```bash
python3 play.py
```
