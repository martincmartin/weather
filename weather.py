# To install:
# brew install pillow
#
# To test:
# cp config.example.toml config.toml, fill in your API keys and locations, run
# python3 weather.py
# then in a browser hit localhost:8998/weather.bmp .

# For stargazing:
# cloudcover "how much of the sky is covered in cloud ranging from 0-100%"
# precipprob
# visibility? "distance at which distant objects are visible"

# https://www.visualcrossing.com/resources/documentation/weather-api/how-to-include-sunrise-sunset-and-moon-phase-data-into-your-api-requests/
# moonphase [at day level, not hourly] "fractional portion through the current moon lunation cycle ranging from 0 (the new moon) to 0.5 (the full moon) and back to 1 (the next new moon)."
# sunrise / sunriseEpoch
# sunset / sunsetEpoch
# moonrise & moonset?

# feelslike

# Clear Sky Chart: https://www.cleardarksky.com/


##########  Unsplash API
# https://api.unsplash.com/photos/random?client_id=$ACCESS_KEY

# Looks like you want the "urls" or "links" element.
# Then take the "raw" element, and add w=800&h=480&fit=crop&crop=faces,center&sat=-100
#
# localhost:8998/pics.bmp

from __future__ import annotations

import argparse
import datetime
import io
import itertools
import json
import math
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import tomllib
import traceback
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from functools import cache, partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import FrameType
from typing import Any
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

import moon
import wordclock

# The screen is 800 x 480.

# The directory of this script, which holds the icons and the font.
HERE = Path(__file__).resolve().parent

# A box on the screen: (left, top, right, bottom).
Box = tuple[int, int, int, int]


# For using LaCrosse weather sensor, with RTL-SDR's dongle, align the antenna
# vertically.  Each arm of the dipole antenna should be aobut 6.5 inches, which
# is a quarter wavelength for 433 MHz.  This is roughly the fully extended
# length of the shorter antenna that comes with the RTL-SDR, so that's handy.  I
# did a simple experiment and verified that vertical is best, which makes sense
# because the temperature sensor is also oriented vertically, so presumably so
# it its antenna.


# Ah, weather APIs.
#
# The weather now comes from Visual Crossing. These notes on the others stay
# here in case we're tempted to use them again (also see the Epilogue in
# README.md).
#
# OpenWeatherMap only has hourly for 2 days.  It has every 3 hours for 5 days,
# but that looks like shit.  tomorrow.io has hourly for 5 days!  But it doesn't
# seem very accurate.  It's saying 80% chance of precip 2.5 days before a big
# Nor'easter that the news has been talking about, and everyone else says 100%.
# Visual Crossing is the only other one worth trying.
#
# weather.gov goes down (DNS entry not found of all things) or times out fairly
# often, so it would be great to move away.  It went down for a week and a half
# straight over winter holidays 2023.  However, the OpenWeatherMaps API only has
# hourly forecasts for two days, not seven.  The hourly forecast for 4 days
# costs $180/mo, so that's out.  I like my seven day temperature graph!  It does
# have 3 hour forecast for 5 days, so I guess we'll settle for that.

# weather.gov's API, see here:
#
# https://weather-gov.github.io/api/general-faqs
#
# To get current weather conditions from OpenWeatherMap:
#
# https://api.openweathermap.org/data/2.5/weather?lat=[your-latitutde]&lon=[your-longitude]&appid=[your-app-id]

# tomorrow.io:
# Minutely is for an hour.
# Hourly is for 5 days.
# The "fields" parameter of its forecast API doesn't seem to actually do
# anything.

# Both OpenWeatherMap and weather.gov give the location's time zone, but
# tomorrow.io doesn't seem to.  Could make a separate call to another service,
# see https://stackoverflow.com/questions/16086962

# A probability of precipitation greather than this will show the raining
# clothing icon.
RAINING_THRESHOLD = 0.33333

PRECIPITATION_GREY = (255 * 2) // 3

# Could go lighter.
AFTERNOON_GREY = (PRECIPITATION_GREY + 256) // 2

AFTERNOON_PRECIPITATION_GREY = PRECIPITATION_GREY * AFTERNOON_GREY // 255

TEMPERATURE_BOX = (800 - 256, 25, 800 - 128, 25 + 128)
ICON_BOX = (800 - 128, 25, 800, 25 + 128)
# The temperature and the icon together: the place name and "Battery Low" are
# centred on it.
CURRENT_BOX = (TEMPERATURE_BOX[0], TEMPERATURE_BOX[1], ICON_BOX[2], ICON_BOX[3])

DAY_GRAPH_BOX = (20, 25, 543, 215)  # the next 24 hours
WEEK_GRAPH_BOX = (20, 270, 543, 460)  # the next 7 days
# Both graphs: an error is written in the middle of it.
GRAPHS_BOX = (DAY_GRAPH_BOX[0], DAY_GRAPH_BOX[1], WEEK_GRAPH_BOX[2], WEEK_GRAPH_BOX[3])

# Aligned to the bottom right.  Width equals sky icon plus temp: 256. For
# height, subtract sky icon = temp = 128, plus a 25 pixel border above those.

MORNING_CLOTHING_BOX = (800 - 256, 128 + 25, 800 - 128, 480)
AFTERNOON_CLOTHING_BOX = (800 - 128, 128 + 25, 800, 480)
CLOTHING_BOX = (800 - (128 + 64), 128 + 25, 800 - 64, 480)

GAP_BETWEEN_GRAPH_AND_LABELS = 10

# For the stargazing display

STARGAZING_GRAPH_BOX = (20, 50, 800 - 20, 480 - 25)

GAP_BETWEEN_NIGHTS = 10

MOON_PHASE_BOX = (0, 10, 60, 70)

# If using rtl_433 to read a physical, outdoor temperature sensor, only listen
# to the model and channel specified here.  ID changes when you change the
# batteries on the sensor, so to support ID, I'd need some kind of pairing
# process.  Currently, mine is the only LaCrosse sensor that I receive, so model
# and channel is more than enough.
RTL_433_MODEL = "LaCrosse-TX141THBv2"
RTL_433_CHANNEL = 0

FONT = str(HERE / "DejaVuSans.ttf")


def print_stack(sig: int, frame: FrameType | None) -> None:
    print("**********  In signal handler, printing stack frame.  **********")
    print("".join(traceback.format_stack(frame)))
    print("**********  Exiting signal handler.  **********", flush=True)


@dataclass(frozen=True)
class Location:
    name: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class Unsplash:
    access_key: str
    query: str  # what /pics.bmp searches for


class Orientation(Enum):
    """How the display is turned. For a portrait search (people, for
    example), turn the display 90 degrees and set orientation in config.toml.
    /pics.bmp follows it; the other pages are drawn for landscape only."""

    LANDSCAPE = "landscape"
    PORTRAIT = "portrait"


@dataclass(frozen=True)
class Config:
    """The private settings, from config.toml. See config.example.toml."""

    visual_crossing_api_key: str
    unsplash: Unsplash | None  # without it, /pics.bmp is off
    home: Location  # /weather.bmp
    stargazing: Location | None  # /stargazing.bmp
    # The other locations, by page: "paris" is /paris.bmp, with the name at
    # the top.
    places: dict[str, Location]
    orientation: Orientation

    @property
    def locations(self) -> list[Location]:
        fixed = [self.home] + ([self.stargazing] if self.stargazing else [])
        return fixed + list(self.places.values())


# The pages that a location cannot take, since the server has them already.
FIXED_PAGES = {"weather", "stargazing", "wordclock", "pics"}


class ConfigError(Exception):
    """The settings file is missing or incomplete."""


def load_config(path: Path) -> Config:
    """Read the settings. Raise ConfigError if the file is missing or
    incomplete."""
    try:
        with path.open("rb") as file:
            data = tomllib.load(file)
        locations = {
            key: Location(
                place["name"], float(place["latitude"]), float(place["longitude"])
            )
            for key, place in data["locations"].items()
        }
        if "home" not in locations:
            raise KeyError("locations.home")
        places = {
            key: location
            for key, location in locations.items()
            if key not in ("home", "stargazing")
        }
        for key in places:
            if not re.fullmatch(r"[a-z0-9-]+", key) or key in FIXED_PAGES:
                raise ValueError(
                    f"locations.{key}: a page name must be lower case letters,"
                    f" digits and hyphens, and not one of {sorted(FIXED_PAGES)}"
                )
        return Config(
            visual_crossing_api_key=data["visual_crossing"]["api_key"],
            unsplash=(
                Unsplash(data["unsplash"]["access_key"], data["unsplash"]["query"])
                if "unsplash" in data
                else None
            ),
            home=locations["home"],
            stargazing=locations.get("stargazing"),
            places=places,
            orientation=Orientation(
                data.get("display", {}).get("orientation", "landscape")
            ),
        )
    except (OSError, tomllib.TOMLDecodeError, KeyError, ValueError) as error:
        raise ConfigError(
            f"Cannot read the settings in {path}: {error!r}. Copy"
            " config.example.toml to config.toml and fill it in."
        ) from error


def centre(box: Box) -> tuple[int, int]:
    return ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)


def scale_to_fit(image: Image.Image, box: Box) -> Image.Image:
    width = box[2] - box[0]
    height = box[3] - box[1]
    factor = min(width / image.size[0], height / image.size[1])
    return image.resize((round(image.size[0] * factor), round(image.size[1] * factor)))


@dataclass(frozen=True)
class Reading:
    """A current temperature for the home page, and how old it is."""

    temperature: float
    age_seconds: float
    battery_ok: bool


# Used to communicate between the main thread and the thread running the RTL_433
# program, which receives the temperature from the LaCrosse outdoor temperature
# sensor.
class LocalWeather:
    def __init__(self) -> None:
        # The time, temperature and battery state of the last message, or None
        # before the first. One tuple, which is replaced whole, so the other
        # thread never sees part of an update, and no lock is needed.
        self.last: tuple[datetime.datetime, float, bool] | None = None

    def set(
        self, time: datetime.datetime, temperature: float, battery_ok: bool
    ) -> None:
        self.last = (time, temperature, battery_ok)

    def reading(self) -> Reading | None:
        last = self.last
        if last is None:
            return None
        time, temperature, battery_ok = last
        age = datetime.datetime.now() - time
        return Reading(temperature, age.total_seconds(), battery_ok)


# If rtl_433 exits (for example, the dongle is unplugged), start it again after
# this many seconds.
RTL_433_RETRY_SECONDS = 60


def rtl_433_thread(executable: str, local_weather: LocalWeather) -> None:
    # Runs for the life of the server. While rtl_433 is down, the home page shows
    # how old the last reading is, and the other pages work as usual.
    while True:
        try:
            rtl_433_loop(executable, local_weather)
            print("***** rtl_433 exited.", flush=True)
        except Exception as e:  # noqa: BLE001 any failure: log it and retry
            print(f'***** RTL 433 thread had exception "{e}"', flush=True)
        print(
            f"***** Starting rtl_433 again in {RTL_433_RETRY_SECONDS} sec.", flush=True
        )
        time.sleep(RTL_433_RETRY_SECONDS)


def rtl_433_loop(executable: str, local_weather: LocalWeather) -> None:
    # pkill and pgrep exit with 1 when no process matches, which is expected.
    subprocess.run(["pkill", "rtl_433"], check=False)
    while subprocess.run(["pgrep", "rtl_433"], check=False).returncode == 0:
        print("***** rtl_433 still running, sleeping.")
        time.sleep(1)

    proc = subprocess.Popen(
        [executable, "-Y", "autolevel", "-F", "json", "-M", "level"],
        shell=False,
        bufsize=1,
        text=True,
        stdout=subprocess.PIPE,
    )
    assert proc.stdout is not None  # stdout=PIPE
    try:
        for raw_line in proc.stdout:
            line = raw_line.strip()
            print(line, flush=True)
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                print("***** Skipping a line from rtl_433 that is not JSON.")
                continue
            if (
                parsed["model"] == RTL_433_MODEL
                # id changes when you change the batteries.
                # and parsed["id"] == RTL_433_ID
                and parsed["channel"] == RTL_433_CHANNEL
            ):
                local_weather.set(
                    datetime.datetime.fromisoformat(parsed["time"]),
                    parsed["temperature_C"] * 1.8 + 32,
                    parsed["battery_ok"] == 1,
                )
    finally:
        proc.kill()  # does nothing if it has exited
        proc.wait()


@dataclass(frozen=True)
class Period:
    """One hour of the forecast."""

    start: datetime.datetime
    end: datetime.datetime
    temp: float
    precipitation: float  # the probability, from 0 to 1
    cloudcover: float  # from 0 to 1
    stargazing: bool  # dark: after sunset, or before 5am

    @property
    def mid(self) -> datetime.datetime:
        return self.start + (self.end - self.start) / 2


@dataclass(frozen=True)
class Forecast:
    timezone: ZoneInfo
    now: int  # epoch seconds of the current conditions
    is_daytime: bool
    periods: list[Period]  # each hour, from the current one
    precipitation: Precipitation  # today's
    wind_speed: float  # today's
    clouds: float  # today's
    is_raining: bool  # now

    def __post_init__(self) -> None:
        if len(self.periods) < 24:
            raise ValueError(f"only {len(self.periods)} hours in the forecast")

    @property
    def next_24_hours(self) -> list[Period]:
        return self.periods[:24]


def load_icon(path: Path, box: Box, mode: str = "L") -> Image.Image:
    return scale_to_fit(Image.open(path).convert(mode), box)


class TemperatureBand(Enum):
    HOT = 0
    WARM = 1
    COOL = 2
    COLD = 3


@cache
def clothing_icons() -> dict[bool, dict[TemperatureBand, Image.Image]]:
    """The clothing icons: when it is raining (True) or not, for each band."""
    return {
        is_raining: {
            member: load_icon(
                HERE
                / "clothing-icons"
                / f"boy-{member.name.lower()}{'-rain' if is_raining else ''}.png",
                CLOTHING_BOX,
            )
            for member in TemperatureBand
        }
        for is_raining in (False, True)
    }


def get_clothing(temperature: float, is_raining: bool) -> Image.Image:
    # Should this take into account sunny vs cloudy?  Direct sun will definitely
    # feel warmer than the measured or forecast temperatures, which are always
    # in the shade.
    clothing = clothing_icons()[is_raining]
    if temperature < 44.5:
        return clothing[TemperatureBand.COLD]
    elif temperature < 70:
        return clothing[TemperatureBand.COOL]
    elif temperature < 79.5:
        return clothing[TemperatureBand.WARM]
    else:
        return clothing[TemperatureBand.HOT]


class Cloudiness(Enum):
    CLOUDY = 0
    MOSTLY_CLOUDY = 1
    MOSTLY_CLEAR = 2
    CLEAR = 3


class DayNight(Enum):
    DAY = 0
    NIGHT = 1


class Precipitation(Enum):
    NONE = 0
    DRIZZLE = 1
    LIGHT_RAIN = 2
    RAINY = 3
    THUNDERSTORMS = 4
    SNOW = 5


def weather_icon_fname(
    day_night: DayNight,
    cloudiness: Cloudiness,
    precipitation: Precipitation,
    windy: bool,
) -> str:
    if precipitation in [
        Precipitation.NONE,
        Precipitation.THUNDERSTORMS,
        Precipitation.SNOW,
    ]:
        windy = False

    if precipitation != Precipitation.NONE and cloudiness != Cloudiness.CLOUDY:
        cloudiness = Cloudiness.MOSTLY_CLOUDY

    if day_night == DayNight.NIGHT and cloudiness == Cloudiness.MOSTLY_CLEAR:
        cloudiness = Cloudiness.MOSTLY_CLOUDY

    day_night_string = (
        "" if cloudiness == Cloudiness.CLOUDY else (day_night.name.lower() + " ")
    )
    cloudiness_string = cloudiness.name.lower().replace("_", " ")
    precipitation_string = (
        (" " + precipitation.name.lower().replace("_", " "))
        if precipitation != Precipitation.NONE
        else ""
    )
    windy_string = " windy" if windy else ""

    return day_night_string + cloudiness_string + precipitation_string + windy_string


@cache
def weather_icons() -> dict[str, Image.Image]:
    icons = {}
    for day_night in DayNight:
        for cloudiness in Cloudiness:
            for precipitation in Precipitation:
                for windy in [True, False]:
                    fname = weather_icon_fname(
                        day_night, cloudiness, precipitation, windy
                    )
                    if fname not in icons:
                        icons[fname] = load_icon(
                            HERE / "weather-icons" / f"{fname}.png",
                            ICON_BOX,
                        )
    return icons


@cache
def moon_icons() -> list[Image.Image]:
    """One image for each equal step of the lunation, from new moon. See
    moon-phase/README.md."""
    return [
        load_icon(path, MOON_PHASE_BOX, "LA")
        for path in sorted((HERE / "moon-phase").glob("phase-*.png"))
    ]


class FetchError(Exception):
    """An HTTP request returned a status other than 200."""


def fetch_bytes(url: str) -> bytes:
    """The body of an HTTP GET of url. Raise an exception unless the status is
    200."""
    with urllib.request.urlopen(url, timeout=15) as response:
        if response.status != 200:
            raise FetchError(f"request failed with status {response.status}")
        body: bytes = response.read()
        return body


def fetch_image(url: str) -> Image.Image:
    start = time.monotonic()
    body = fetch_bytes(url)
    fetch_end = time.monotonic()
    image = Image.open(io.BytesIO(body))
    parse_end = time.monotonic()
    print(
        f"Time to fetch image: {fetch_end - start} + {parse_end - fetch_end} = {parse_end - start} sec."
    )
    return image


def fetch_json(url: str) -> dict[str, Any]:
    start = time.monotonic()
    body = fetch_bytes(url)
    fetch_end = time.monotonic()
    result: dict[str, Any] = json.loads(body.decode("utf-8"))
    parse_end = time.monotonic()
    print(
        f"Time to fetch & parse: {fetch_end - start} + {parse_end - fetch_end} = {parse_end - start} sec."
    )
    return result


class CachedForecast:
    """The forecast from url, fetched again when it is older than
    cache_time_in_sec. A failed fetch is not kept, so the next request tries
    again."""

    def __init__(self, url: str, cache_time_in_sec: float) -> None:
        self.url = url
        self.cache_time_in_sec = cache_time_in_sec
        # The time of the fetch, and its forecast.
        self.cached: tuple[float, Forecast] | None = None
        # Each request runs in its own thread. The lock makes a second request
        # wait for the first one's fetch, instead of fetching again.
        self.lock = threading.Lock()

    def get(self) -> Forecast:
        with self.lock:
            current_time = time.monotonic()
            if (
                self.cached is None
                or current_time > self.cached[0] + self.cache_time_in_sec
            ):
                # There's evidence that we're running out of memory on the
                # Raspberry Pi 3.  Free all this data before creating the new one.
                self.cached = None
                self.cached = (current_time, get_forecast(fetch_json(self.url)))
            return self.cached[1]


def icon_to_precipitation(icon: str) -> Precipitation:
    # https://www.visualcrossing.com/resources/documentation/weather-api/defining-icon-set-in-the-weather-api/
    if icon.startswith("snow"):
        return Precipitation.SNOW
    if icon.startswith("thunder"):
        return Precipitation.THUNDERSTORMS
    if icon.startswith(("rain", "showers")):
        # TODO: distingoush drizzle vs light rain vs rainy.  Maybe use inches/hr
        # of rain?
        return Precipitation.RAINY
    return Precipitation.NONE


def visual_crossing_forecast(location: Location, api_key: str) -> CachedForecast:
    # Visual Crossing documentation:
    # https://www.visualcrossing.com/resources/documentation/weather-api/timeline-weather-api/
    #
    # 1000 free 15-day-forecasts for one location per day.
    # https://www.visualcrossing.com/resources/documentation/weather-data/understanding-and-optimizing-the-visual-crossing-weather-pay-as-you-go-plan/
    return CachedForecast(
        f"https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline/{location.latitude}%2C{location.longitude}?unitGroup=us&key={api_key}&contentType=json&iconSet=icons2",
        3.5 * 60,
    )


def get_forecast(result: dict[str, Any]) -> Forecast:
    """The forecast in a Visual Crossing timeline result."""
    timezone = ZoneInfo(result["timezone"])

    today = result["days"][0]
    # Note that these conditions can be up to an hour delayed, as some places
    # only report current conditions once an hour, with a delay of 30 minutes.
    # SMH.
    current = result["currentConditions"]

    # Epoch values are always based around the UTC time zone (sometimes known as GMT).
    #
    now = current["datetimeEpoch"]

    is_daytime = current["sunriseEpoch"] <= now <= current["sunsetEpoch"]

    periods = []
    for day in result["days"]:
        # Note that it takes around an hour after sunset to get dark.
        sunset = day["sunsetEpoch"]
        for hour in day["hours"]:
            # Epoch values are always based around the UTC time zone (sometimes known as GMT).
            start_epoch = hour["datetimeEpoch"]
            if start_epoch + 60 * 60 > now:
                start = datetime.datetime.fromtimestamp(start_epoch, timezone)
                end = start + datetime.timedelta(hours=1)

                # The latest anyone would conceivably be awake and star gazing is
                # 5am, and that's also around the earliest sunrise (5:06am) in
                # mid June.  So we can cut off the evening then.  So each day
                # will go from sunset to 5am.
                stargazing = start_epoch > sunset or end.hour <= 5
                periods.append(
                    Period(
                        start,
                        end,
                        hour["temp"],
                        (hour["precipprob"] or 0.0) / 100.0,
                        hour["cloudcover"] / 100.0,
                        stargazing,
                    )
                )

    return Forecast(
        timezone,
        now,
        is_daytime,
        periods,
        icon_to_precipitation(today["icon"]),
        today["windspeed"],
        today["cloudcover"],
        bool(current["precip"] and current["precip"] > 0),
    )


def round_up_to_next_6_hours(input_datetime: datetime.datetime) -> datetime.datetime:
    # Calculate the number of hours to the next multiple of 6
    hours_to_next_6 = (6 - input_datetime.hour % 6) % 6

    timedelta_to_next_6 = timedelta(hours=hours_to_next_6)

    # Round up the input datetime to the next multiple of 6 hours
    rounded_datetime = input_datetime + timedelta_to_next_6
    return rounded_datetime.replace(minute=0, second=0, microsecond=0)


def round_to_next_day(input_datetime: datetime.datetime) -> datetime.datetime:
    truncated = input_datetime.replace(hour=0, minute=0, second=0, microsecond=0)
    if truncated < input_datetime:
        return truncated + timedelta(days=1)
    else:
        return truncated


def time_to_x(
    time: datetime.datetime, start: float, end: float, left: float, right: float
) -> float:
    """The x of time on a time axis from start (at left) to end (at right),
    both in epoch seconds."""
    timestamp = time.timestamp()
    assert timestamp >= start
    assert timestamp <= end
    return (timestamp - start) / (end - start) * (right - left) + left


def graph_layout(
    rect: Box,
) -> tuple[ImageFont.FreeTypeFont, tuple[float, float, float, float]]:
    """The font for a graph's labels, and the box (left, top, right, bottom)
    inside rect that is left for the graph."""
    font = ImageFont.truetype(FONT, (rect[2] - rect[0]) // 19)

    # This code for adjusting for text size is only approximate, so in practice,
    # when you change font size, you still need to adjust the rect parameter
    # passed into plot_graph().  Oh well.

    y_label_bbox = font.getbbox("99")
    y_label_width = y_label_bbox[2] - y_label_bbox[0]

    x_label_bbox = font.getbbox("Sun")
    x_label_height = x_label_bbox[3] - x_label_bbox[1]

    return font, (
        rect[0] + y_label_width,
        rect[1],
        rect[2],
        rect[3] - x_label_height - GAP_BETWEEN_GRAPH_AND_LABELS,
    )


def plot_graph(periods: list[Period], image: Image.Image, rect: Box) -> None:
    multiday = periods[-1].end - periods[0].start > datetime.timedelta(hours=36)
    connected = len(periods) > 48

    min_temp = min(p.temp for p in periods)
    max_temp = max(p.temp for p in periods)

    low_temp = math.floor(min_temp / 5) * 5
    # If every temperature is the same multiple of 5, low_temp equals it too;
    # the scale needs some height.
    high_temp = max(math.ceil(max_temp / 5) * 5, low_temp + 5)

    min_time = min(p.start for p in periods).timestamp()
    max_time = max(p.end for p in periods).timestamp()

    draw = ImageDraw.Draw(image)
    font, (graph_left, graph_top, graph_right, graph_bottom) = graph_layout(rect)

    # Map low_temp to bottom of rect, and high_temp to top.
    def temp_to_y(temp: float) -> float:
        return (temp - low_temp) / (high_temp - low_temp) * (
            graph_top - graph_bottom
        ) + graph_bottom

    to_x = partial(
        time_to_x, start=min_time, end=max_time, left=graph_left, right=graph_right
    )

    #####  Draw the % precipitation polygon.
    precip_polygon: list[tuple[float, float]] = [(graph_left, graph_bottom)]
    for period in periods:
        y = period.precipitation * (graph_top - graph_bottom) + graph_bottom
        precip_polygon += [(to_x(period.start), y), (to_x(period.end), y)]

    precip_polygon.append((graph_right, graph_bottom))
    draw.polygon(precip_polygon, fill=PRECIPITATION_GREY)

    #####  Draw horizontal lines & labels for temperatures.
    # Should probably decide between every 10 degrees and every 5 degress based
    # on e.g. whatever gives closest to 5 lines.
    for temp in range(low_temp, high_temp + 1, 10):
        y = temp_to_y(temp)
        draw.line((graph_left, y, graph_right, y), fill=128)
        draw.text((graph_left - 3, y), str(temp), font=font, fill=0, anchor="rm")

    #####  Draw vertical lines & labels for times
    start_datetime = min(p.start for p in periods)
    end_datetime = max(p.end for p in periods)
    if multiday:
        this_datetime = round_to_next_day(start_datetime)

        while this_datetime < end_datetime:
            x = to_x(this_datetime)
            draw.line((x, graph_top, x, graph_bottom), fill=128)

            text_datetime = this_datetime + timedelta(hours=12)
            if text_datetime < end_datetime:
                draw.text(
                    (to_x(text_datetime), graph_bottom + GAP_BETWEEN_GRAPH_AND_LABELS),
                    this_datetime.strftime("%a"),
                    font=font,
                    fill=0,
                    anchor="ma",
                )
            this_datetime += timedelta(days=1)
    else:
        this_datetime = round_up_to_next_6_hours(start_datetime)

        while this_datetime < end_datetime:
            x = to_x(this_datetime)

            if this_datetime.hour == 0:
                draw.line((x, graph_top, x, graph_bottom), fill=128)

            if this_datetime.hour == 12:
                text = "noon"
            elif this_datetime.hour == 0:
                text = this_datetime.strftime("%a")
            else:
                text = this_datetime.strftime("%-I%p").lower()

            draw.text(
                (x, graph_bottom + GAP_BETWEEN_GRAPH_AND_LABELS),
                text,
                font=font,
                fill=0,
                anchor="ma",
            )

            this_datetime += timedelta(hours=6)

    # Draw the actual temperatures.
    if connected:
        xy = [(to_x(period.mid), temp_to_y(period.temp)) for period in periods]
        draw.line(xy, fill=0, width=1)
    else:
        for period in periods:
            y = temp_to_y(period.temp)
            left = to_x(period.start)
            right = to_x(period.end)

            if period.start.hour == 15:
                draw.rectangle(
                    (left, graph_top, right, graph_bottom - 1),
                    fill=AFTERNOON_GREY,
                )
                if period.precipitation > 0:
                    precipitation_y = (
                        period.precipitation * (graph_top - graph_bottom) + graph_bottom
                    )
                    draw.rectangle(
                        (left, precipitation_y, right, graph_bottom - 1),
                        fill=AFTERNOON_PRECIPITATION_GREY,
                    )

            draw.line(
                (left, y, right, y),
                fill=0,
                width=3,
            )


def draw_icon(forecast: Forecast, image: Image.Image) -> None:
    # I read somewhere that 20 mph is the threshold for "windy".
    windy = forecast.wind_speed > 20

    if forecast.clouds <= 25:
        cloudiness = Cloudiness.CLEAR
    elif forecast.clouds <= 50:
        cloudiness = Cloudiness.MOSTLY_CLEAR
    elif forecast.clouds <= 75:
        cloudiness = Cloudiness.MOSTLY_CLOUDY
    else:
        cloudiness = Cloudiness.CLOUDY

    fname = weather_icon_fname(
        DayNight.DAY if forecast.is_daytime else DayNight.NIGHT,
        cloudiness,
        forecast.precipitation,
        windy,
    )
    icon = weather_icons()[fname]

    image.paste(icon, box=(ICON_BOX[0], ICON_BOX[1]))


def load_forecast(cached: CachedForecast) -> Forecast | Exception:
    """The forecast, or the error that a page shows in its place."""
    try:
        return cached.get()
    except Exception as error:  # noqa: BLE001 the page shows the error instead
        print("***** Could not get the forecast:", error)
        print(traceback.format_exc(), flush=True)
        return error


def draw_error(image: Image.Image, error: Exception) -> None:
    """Write error in the middle of the graphs, unless it is a 502 (Bad
    Gateway), which Visual Crossing gives now and then for a short time."""
    if isinstance(error, urllib.error.HTTPError) and error.code == 502:
        return
    ImageDraw.Draw(image).text(
        centre(GRAPHS_BOX),
        str(error),
        font=ImageFont.truetype(FONT, 32),
        fill=0,
        anchor="mm",
    )


def paste_image(image: Image.Image, small_image: Image.Image, box: Box) -> None:
    """Paste small_image into image, centred in box."""
    image.paste(
        small_image,
        box=(
            (box[0] + box[2] - small_image.size[0]) // 2,
            (box[1] + box[3] - small_image.size[1]) // 2,
        ),
    )


def get_image(
    forecast_source: CachedForecast,
    sensor: LocalWeather | None,
    name: str | None,
) -> Image.Image:
    """A weather page. sensor is the outdoor temperature sensor, if there is
    one. name is None for the home page; other pages show the name and the
    local time at the top."""
    image = Image.new("L", (800, 480), 255)
    draw = ImageDraw.Draw(image)

    forecast = load_forecast(forecast_source)

    ##### Get the current temperature.
    reading: Reading | None
    if sensor is not None:
        reading = sensor.reading()  # None before the first message
    elif isinstance(forecast, Exception):
        reading = None
    else:
        reading = Reading(
            forecast.next_24_hours[0].temp, age_seconds=0.0, battery_ok=True
        )
    battery_ok = reading is None or reading.battery_ok

    # Without a forecast, the clothing is for no rain: the page must not look
    # as if it knows that it will rain.
    is_raining = not isinstance(forecast, Exception) and forecast.is_raining
    text = "--"
    current_icon: Image.Image | None = None
    if reading is not None:
        if reading.age_seconds < 5 * 60:
            text = f"{round(reading.temperature)}\N{DEGREE SIGN}"
            current_icon = get_clothing(reading.temperature, is_raining)
        elif reading.age_seconds < 100 * 60:
            text = f"{round(reading.age_seconds / 60)}m"

    ##### Get the afternoon temperature when kids come home from school.
    school_icon = None
    if not isinstance(forecast, Exception):
        # 3:40pm at the location, which can be in another time zone.
        school = datetime.datetime.now(forecast.timezone).replace(
            hour=15, minute=40, second=0, microsecond=0
        )
        # Skip the first period, since if they're comming home from school
        # within the hour, we want the actual temperature & rain, not forecast.
        school_period = next(
            (p for p in forecast.next_24_hours[1:] if p.start < school < p.end), None
        )
        if school_period is not None:
            school_icon = get_clothing(
                school_period.temp, school_period.precipitation > RAINING_THRESHOLD
            )

    ##### Now draw the two clothing icons
    if current_icon is None:
        if school_icon is not None:
            paste_image(image, school_icon, AFTERNOON_CLOTHING_BOX)
    else:
        if school_icon is None or current_icon == school_icon:
            paste_image(image, current_icon, CLOTHING_BOX)
        else:
            paste_image(image, current_icon, MORNING_CLOTHING_BOX)
            paste_image(image, school_icon, AFTERNOON_CLOTHING_BOX)

    font = ImageFont.truetype(FONT, 64)

    if battery_ok:
        draw.text(
            centre(TEMPERATURE_BOX),
            text,
            font=font,
            fill=0,
            anchor="mm",
        )

        if not isinstance(forecast, Exception):
            draw_icon(forecast, image)
    else:
        draw.multiline_text(
            centre(CURRENT_BOX), "Battery\nLow", font=font, fill=0, anchor="mm"
        )
    font = ImageFont.truetype(FONT, 32)
    if isinstance(forecast, Exception):
        draw_error(image, forecast)
    else:
        plot_graph(forecast.next_24_hours, image, DAY_GRAPH_BOX)
        plot_graph(forecast.periods[: (7 * 24)], image, WEEK_GRAPH_BOX)

        if name is not None:
            now = datetime.datetime.fromtimestamp(forecast.now, forecast.timezone)

            x, y = centre(TEMPERATURE_BOX)
            draw.text(
                (x, y + 48),
                now.strftime("%-I:%M%p").lower(),
                font=font,
                fill=0,
                anchor="mm",
            )

    if name is not None:
        draw.text(
            (centre(CURRENT_BOX)[0], 0),
            name,
            font=font,
            fill=0,
            anchor="ma",
        )
    return image


def get_moon_icon(phase: float) -> Image.Image:
    # The phase is a fraction of the lunation. A phase near 1 rounds to the
    # count, which is new moon again: index 0.
    icons = moon_icons()
    index = round(phase * len(icons)) % len(icons)
    return icons[index]


def night_of(period: Period) -> datetime.date:
    """The day on which the night of period begins. The nights split at noon,
    so a period before noon belongs to the night that began the day before."""
    start = period.start
    return start.date() - timedelta(days=1 if start.hour < 12 else 0)


def plot_stargazing(periods: list[Period], image: Image.Image, rect: Box) -> None:
    nights = [list(night) for _, night in itertools.groupby(periods, night_of)]

    draw = ImageDraw.Draw(image)
    font, (graph_left, graph_top, graph_right, graph_bottom) = graph_layout(rect)

    #####  Draw the % cloud cover polygons.
    # There are len(night) nights, with len(night) - 1 gaps between them.
    night_width = (
        (graph_right - graph_left) - GAP_BETWEEN_NIGHTS * (len(nights) - 1)
    ) / len(nights)

    for night_index, night in enumerate(nights):
        min_time = min(p.start for p in night).timestamp()
        max_time = max(p.end for p in night).timestamp()

        night_left = graph_left + (night_width + GAP_BETWEEN_NIGHTS) * night_index
        night_right = night_left + night_width

        to_x = partial(
            time_to_x, start=min_time, end=max_time, left=night_left, right=night_right
        )

        cloud_polygon = [(to_x(night[0].start), graph_bottom)]
        for period in night:
            y = period.cloudcover * (graph_top - graph_bottom) + graph_bottom
            cloud_polygon += [(to_x(period.start), y), (to_x(period.end), y)]
        cloud_polygon.append((to_x(night[-1].end), graph_bottom))
        draw.polygon(cloud_polygon, fill=PRECIPITATION_GREY)

        # Draw midnight line
        midnight = round_to_next_day(night[0].start)
        if midnight.timestamp() <= max_time:
            x = to_x(midnight)
            draw.line((x, graph_top, x, graph_bottom), fill=128)

            # The moon phase at midnight, centred on the midnight line.
            # Visual Crossing gives one moon phase a day, to 2 digits, so
            # compute it.
            moon_image = get_moon_icon(moon.phase(midnight))
            image.paste(
                moon_image,
                box=(round(x - moon_image.width / 2), MOON_PHASE_BOX[1]),
                mask=moon_image,
            )

            # Draw text for day of the week
            x = night_left + night_width + GAP_BETWEEN_NIGHTS / 2
            if x < graph_right:
                draw.text(
                    (x, graph_bottom + GAP_BETWEEN_GRAPH_AND_LABELS),
                    midnight.strftime("%a"),
                    font=font,
                    fill=0,
                    anchor="ma",
                )


def stargazing_periods(periods: list[Period], now: datetime.datetime) -> list[Period]:
    """The night periods of the 7 nights to show, from now (a time in the
    location's time zone)."""
    # The latest I could conceivably leave to go stargazing is 8pm, arriving
    # around 10pm.  So, if it's after 8pm today, the first night I'll show will
    # be tomorrow's, otherwise tonight's.  A night runs to 5am, and the nights
    # split at noon, so tonight ends at noon tomorrow.
    if now.hour >= 20:
        noon_tomorrow = (now + timedelta(days=1)).replace(
            hour=12, minute=0, second=0, microsecond=0
        )
        periods = [p for p in periods if p.start >= noon_tomorrow]
    periods = [period for period in periods if period.stargazing]
    if not periods:
        return []
    # Whole nights, not a count of hours, so that the last night is not a
    # sliver.
    end = datetime.datetime.combine(
        night_of(periods[0]) + timedelta(days=7),
        datetime.time(12),
        periods[0].start.tzinfo,
    )
    return [period for period in periods if period.start < end]


def get_stargazing(forecast_source: CachedForecast) -> Image.Image:
    image = Image.new("L", (800, 480), 255)

    forecast = load_forecast(forecast_source)
    if isinstance(forecast, Exception):
        draw_error(image, forecast)
        return image

    # This is day (night) based, since we don't care about cloud cover during
    # the day.

    periods = stargazing_periods(
        forecast.periods, datetime.datetime.now(forecast.timezone)
    )
    plot_stargazing(periods, image, STARGAZING_GRAPH_BOX)
    return image


def get_unsplash(unsplash: Unsplash, orientation: Orientation) -> str:
    """The URL of a random black and white photo, the size of the screen as
    the viewer sees it."""
    query = urllib.parse.quote(unsplash.query)
    rando = fetch_json(
        f"https://api.unsplash.com/photos/random?client_id={unsplash.access_key}&query={query}"
    )
    raw: str = rando["urls"]["raw"]
    width, height = upright_size(orientation)
    return raw + f"&w={width}&h={height}&fit=crop&crop=faces,center&sat=-100"


def upright_size(orientation: Orientation) -> tuple[int, int]:
    """The size of the screen as the viewer sees it."""
    return (800, 480) if orientation is Orientation.LANDSCAPE else (480, 800)


def portrait_to_screen(image: Image.Image) -> Image.Image:
    """An upright portrait image, turned to fit the screen's 800 x 480 pixels
    when the display is turned to portrait."""
    return image.transpose(Image.Transpose.ROTATE_90)


def portrait_notice() -> Image.Image:
    """The page for a display turned to portrait, in place of a page that is
    drawn for landscape only."""
    image = Image.new("L", upright_size(Orientation.PORTRAIT), 255)
    ImageDraw.Draw(image).multiline_text(
        centre((0, 0, *image.size)),
        "This page needs\na landscape\ndisplay.\n\nSee orientation\nin config.toml.",
        font=ImageFont.truetype(FONT, 40),
        fill=0,
        anchor="mm",
        align="center",
    )
    return portrait_to_screen(image)


class Dashboard:
    """What the server needs for each request: the settings, a cached forecast
    query for each location, and the outdoor sensor, if there is one."""

    def __init__(self, config: Config, sensor: LocalWeather | None) -> None:
        self.config = config
        self.sensor = sensor
        self.forecasts = {
            location: visual_crossing_forecast(location, config.visual_crossing_api_key)
            for location in config.locations
        }
        # The extra locations, by the path of their page: "/paris.bmp".
        self.place_pages = {
            f"/{key}.bmp": location for key, location in config.places.items()
        }

    def landscape_page(self, path: str) -> Callable[[], Image.Image] | None:
        """How to draw the page at path, if it is one of the pages that are
        drawn for landscape only."""
        config = self.config
        if path == "/weather.bmp":
            return partial(get_image, self.forecasts[config.home], self.sensor, None)
        if place := self.place_pages.get(path):
            return partial(get_image, self.forecasts[place], None, place.name)
        if path == "/stargazing.bmp" and config.stargazing:
            return partial(get_stargazing, self.forecasts[config.stargazing])
        if path == "/wordclock.bmp":
            return lambda: wordclock.render(datetime.datetime.now())
        return None


class WeatherHTTPRequestHandler(BaseHTTPRequestHandler):
    def __init__(self, *args: Any, dashboard: Dashboard, **kwargs: Any) -> None:
        # Before super().__init__, which handles the request.
        self.dashboard = dashboard
        super().__init__(*args, **kwargs)

    def send_image(self, image: Image.Image) -> None:
        """Send image as 1-bit, as the e-ink display shows it, so that a page
        seen in a browser is the same."""
        # Encode first, so that the length is known, and a failure gives a 500
        # and not a cut-off 200.
        buffer = io.BytesIO()
        image.convert("1").save(buffer, format="BMP")
        body = buffer.getbuffer()
        self.send_response(200)
        self.send_header("Content-type", "image/bmp")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        request_start = time.monotonic()
        config = self.dashboard.config
        print(f"***** GET {self.path}", flush=True)
        try:
            if self.path == "/pics.bmp" and config.unsplash:
                url = get_unsplash(config.unsplash, config.orientation)
                print(f"Unsplash url: {url}")
                if config.orientation is Orientation.LANDSCAPE:
                    self.send_response(307)
                    self.send_header("Location", url)
                    self.end_headers()
                else:
                    # Unsplash has no way to rotate images, so fetch it and
                    # rotate it here.
                    self.send_image(portrait_to_screen(fetch_image(url)))
            elif (draw_page := self.dashboard.landscape_page(self.path)) is None:
                self.send_error(404, explain="Don't hack me go away.")
            elif config.orientation is Orientation.PORTRAIT:
                self.send_image(portrait_notice())
            else:
                image = draw_page()
                print(f"Got image after {time.monotonic() - request_start} sec")
                self.send_image(image)
                print(
                    f"Done sending image response in {time.monotonic() - request_start} sec.",
                    flush=True,
                )
        except Exception:  # noqa: BLE001 answer 500, not a dropped connection
            print("***** Got exception!", flush=True)
            print(traceback.format_exc(), flush=True)
            self.send_error(500, explain="Python code threw an exception.")


def run_http_server(dashboard: Dashboard) -> None:
    server_address = ("", 8998)
    print("Launching server.", flush=True)
    httpd = ThreadingHTTPServer(
        server_address, partial(WeatherHTTPRequestHandler, dashboard=dashboard)
    )
    print("Listening.", flush=True)
    httpd.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="weather",
        description="Serve weather dashboard for invisible-computer e-ink display",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=HERE / "config.toml",
        help="the private settings: API keys and locations (default: config.toml"
        " next to this script)",
    )
    arguments = parser.parse_args()
    try:
        config = load_config(arguments.config.resolve())
    except ConfigError as error:
        print(error, file=sys.stderr)
        sys.exit(1)

    signal.signal(signal.SIGUSR1, print_stack)

    # Load the icons now, so that a missing file stops the server at start.
    weather_icons()
    clothing_icons()
    moon_icons()

    executable = shutil.which("rtl_433")
    print(f"have_rtl_433={executable!r}")
    sensor = None
    if executable:
        sensor = LocalWeather()
        # A daemon thread, so that it does not keep the process alive after the
        # server stops (for example, on Ctrl-C).
        threading.Thread(
            target=rtl_433_thread, args=(executable, sensor), daemon=True
        ).start()

    run_http_server(Dashboard(config, sensor))


if __name__ == "__main__":
    main()
