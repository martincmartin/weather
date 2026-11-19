# To install:
# brew install pillow
#
# To test:
# cp config.example.toml config.toml, fill in your API keys and locations, run
# python3 weather.py
# then in a browser hit localhost:8998/weather.bmp .

# For the dogs pictures, to shrink, crop & convert
"""
for file in orig/*.jpg; do
  magick convert "$file" -resize 800x480^ \
                  -gravity Center  \
                  -extent 800x480  \
                  -dither FloydSteinberg \
                  -remap pattern:gray50 \
        prepped/$(basename "$file" .jpg).bmp
done
"""

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

import re
import urllib.parse
import urllib.request
import io
import json
from datetime import timedelta
import datetime
import time
from PIL import Image, ImageDraw, ImageFont
import math
import sys
from zoneinfo import ZoneInfo
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from enum import Enum
import glob
import os
import shutil
import subprocess
import threading
import time
import argparse
import signal
import traceback
import tomllib
from dataclasses import dataclass
from pathlib import Path

import moon
import wordclock

# The screen is 800 x 480.


# For using LaCrosse weather sensor, with RTL-SDR's dongle, align the antenna
# vertically.  Each arm of the dipole antenna should be aobut 6.5 inches, which
# is a quarter wavelength for 433 MHz.  This is roughly the fully extended
# length of the shorter antenna that comes with the RTL-SDR, so that's handy.  I
# did a simple experiment and verified that vertical is best, which makes sense
# because the temperature sensor is also oriented vertically, so presumably so
# it its antenna.


# Ah, weather APIs.
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

# Uses weather.gov, see here:
#
# https://weather-gov.github.io/api/general-faqs
#
# To get current weather conditions from OpenWeatherMap:
#
# https://api.openweathermap.org/data/2.5/weather?lat=[your-latitutde]&lon=[your-longitude]&appid=[your-app-id]

# tomorrow.io:
# Minutely is for an hour.
# Hourly is for 5 days.

# Both OpenWeatherMap and weather.gov provide this, but tomorrow.io doesn't seem
# to.  Could make a separate call to another service, see
# https://stackoverflow.com/questions/16086962

# A probability of precipitation greather than this will show the raining
# clothing icon.
RAINING_THRESHOLD = 0.33333

PRECIPITATION_GREY = (255 * 2) // 3

# Could go lighter.
AFTERNOON_GREY = (PRECIPITATION_GREY + 256) // 2

AFTERNOON_PRECIPITATION_GREY = PRECIPITATION_GREY * AFTERNOON_GREY // 255

TEMPERATURE_BOX = (800 - 256, 25, 800 - 128, 25 + 128)
ICON_BOX = (800 - 128, 25, 800, 25 + 128)

# Aligned to the bottom right.  Width equals sky icon plus temp: 256. For
# height, subtract sky icon = temp = 128, plus a 25 pixel border above those.

MORNING_CLOTHING_BOX = (800 - 256, 128 + 25, 800 - 128, 480)
AFTERNOON_CLOTHING_BOX = (800 - 128, 128 + 25, 800, 480)
CLOTHING_BOX = (800 - (128 + 64), 128 + 25, 800 - 64, 480)

GAP_BETWEEN_GRAPH_AND_LABELS = 10

# For the stargazing display

GAP_BETWEEN_NIGHTS = 10

MOON_PHASE_BOX = (0, 10, 60, 70)

# If using rtl_433 to read a physical, outdoor temperature sensor, only listen
# to the model and channel specified here.  ID changes when you change the
# batteries on the sensor, so to support ID, I'd need some kind of pairing
# process.  Currently, mine is the only LaCrosse sensor that I receive, so model
# and channel is more than enough.
RTL_433_MODEL = "LaCrosse-TX141THBv2"
RTL_433_CHANNEL = 0

FONT = "./DejaVuSans.ttf"
# FONT = "Pillow/Tests/fonts/DejaVuSans/DejaVuSans.ttf"


LANDSCAPE = True


def print_stack(sig, frame):
    print("**********  In signal handler, printing stack frame.  **********")
    print("".join(traceback.format_stack(frame)))
    print("**********  Exiting signal handler.  **********", flush=True)


signal.signal(signal.SIGUSR1, print_stack)

parser = argparse.ArgumentParser(
    prog="weather",
    description="Serve weather dashboard for invisible-computer e-ink display",
)
parser.add_argument(
    "--config",
    type=Path,
    default=Path(__file__).resolve().parent / "config.toml",
    help="the private settings: API keys and locations (default: config.toml"
    " next to this script)",
)
args = parser.parse_args()
CONFIG_PATH = args.config.resolve()

# Set current directory to the directory containing this script.
os.chdir(os.path.dirname(os.path.abspath(sys.argv[0])))


def parse_datetime(string):
    return datetime.datetime.fromisoformat(string.replace("Z", "+00:00"))


@dataclass(frozen=True)
class Location:
    name: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class Unsplash:
    access_key: str
    query: str  # what /pics.bmp searches for


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

    @property
    def locations(self) -> list[Location]:
        fixed = [self.home] + ([self.stargazing] if self.stargazing else [])
        return fixed + list(self.places.values())


# The pages that a location cannot take, since the server has them already.
FIXED_PAGES = {"weather", "stargazing", "wordclock", "pics", "pics_old"}


def load_config(path: Path) -> Config:
    """Read the settings, or exit with a message if the file is missing or
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
        )
    except (OSError, tomllib.TOMLDecodeError, KeyError, ValueError) as error:
        print(
            f"Cannot read the settings in {path}: {error!r}. Copy"
            " config.example.toml to config.toml and fill it in.",
            file=sys.stderr,
        )
        sys.exit(1)


CONFIG = load_config(CONFIG_PATH)
PLACE_PAGES = {f"/{key}.bmp": location for key, location in CONFIG.places.items()}


def scale_to_fit(image, box):
    width = box[2] - box[0]
    height = box[3] - box[1]
    factor = min(width / image.size[0], height / image.size[1])
    return image.resize(
        (int(round(image.size[0] * factor)), int(round(image.size[1] * factor)))
    )


# Used to communicate between the main thread and the thread running the RTL_433
# program, which receives temperature (and humidity, not used) from the LaCrosse
# outdoor temperature sensor.
class LocalWeather:
    def __init__(self):
        self.lock = threading.Lock()
        self.time = datetime.datetime(2000, 1, 1)
        self.temperature = 999
        self.humidity = 999
        self.battery_ok = True

    def set(self, time, temperature, humidity, battery_ok):
        with self.lock:
            self.time = time
            self.temperature = temperature
            self.humidity = humidity
            self.battery_ok = battery_ok


local_weather = LocalWeather()


def rtl_433_thread(local_weather: LocalWeather):
    try:
        rtl_433_loop(local_weather)
    except Exception as e:
        print(f'***** RTL 433 thread had exception "{str(e)}"')
    except:
        print(f"***** Caught unknown exception in RTL 433 thread! {sys.exc_info()[0]}")

    print("*****  rtl_433 thread ended!", flush=True)
    sys.exit(2)


def rtl_433_loop(local_weather: LocalWeather):
    subprocess.run(["pkill", "rtl_433"])
    while subprocess.run(["pgrep", "rtl_433"]).returncode == 0:
        print("***** rtl_433 still running, sleeping.")
        time.sleep(1)

    proc = subprocess.Popen(
        [have_rtl_433, "-Y", "autolevel", "-F", "json", "-M", "level"],
        shell=False,
        bufsize=1,
        text=True,
        stdout=subprocess.PIPE,
    )
    for line in proc.stdout:
        line = line.strip()
        print(line, flush=True)
        parsed = json.loads(line)
        if (
            parsed["model"] == RTL_433_MODEL
            # id changes when you change the batteries.
            # and parsed["id"] == RTL_433_ID
            and parsed["channel"] == RTL_433_CHANNEL
        ):
            local_weather.set(
                parse_datetime(parsed["time"]),
                parsed["temperature_C"] * 1.8 + 32,
                parsed["humidity"],
                parsed["battery_ok"] == 1,
            )


have_rtl_433 = shutil.which("rtl_433")
print(f"{have_rtl_433=}")
if have_rtl_433:
    thread = threading.Thread(target=rtl_433_thread, args=(local_weather,))
    thread.start()


class Period:
    def __init__(self, start, end, temp, precipitation, cloudcover, stargazing):
        self.start = start
        self.end = end
        self.temp = temp
        self.precipitation = precipitation
        self.cloudcover = cloudcover
        self.mid = self.start + (self.end - self.start) / 2
        self.stargazing = stargazing

    def __repr__(self):
        return f"{self.start} to {self.end} temp: {self.temp} cloud: {self.cloudcover}"


class Forecast:
    def __init__(
        self,
        timezone,
        now,
        isDaytime,
        periods,
        long_range_forecast,
        precipitation,
        wind_speed,
        clouds,
        is_raining,
    ):
        assert len(periods) == 24
        self.timezone = timezone
        self.now = now
        self.isDaytime = isDaytime
        self.periods = periods
        self.long_range_forecast = long_range_forecast
        self.precipitation = precipitation
        self.wind_speed = wind_speed
        self.clouds = clouds
        self.is_raining = is_raining


def load_icon(fname, box, mode="L"):
    return scale_to_fit(Image.open(fname).convert(mode), box)


class TemperatureBand(Enum):
    HOT = 0
    WARM = 1
    COOL = 2
    COLD = 3


clothing_not_raining = {
    member: load_icon(f"clothing-icons/boy-{member.name.lower()}.png", CLOTHING_BOX)
    for member in TemperatureBand
}

clothing_raining = {
    member: load_icon(
        f"clothing-icons/boy-{member.name.lower()}-rain.png", CLOTHING_BOX
    )
    for member in TemperatureBand
}


def get_clothing(temperature, is_raining):
    # Should this take into account sunny vs cloudy?  Direct sun will definitely
    # feel warmer than the measured or forecast temperatures, which are always
    # in the shade.
    clothing = clothing_raining if is_raining else clothing_not_raining
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
):
    if precipitation in [
        Precipitation.NONE,
        Precipitation.THUNDERSTORMS,
        Precipitation.SNOW,
    ]:
        windy = False

    if precipitation != Precipitation.NONE:
        if cloudiness != Cloudiness.CLOUDY:
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


def load_weather_icons():
    weather_icons = {}
    for day_night in DayNight:
        for cloudiness in Cloudiness:
            for precipitation in Precipitation:
                for windy in [True, False]:
                    fname = weather_icon_fname(
                        day_night, cloudiness, precipitation, windy
                    )
                    if fname not in weather_icons:
                        weather_icons[fname] = load_icon(
                            f"weather-icons/{fname}.png",
                            ICON_BOX,
                        )
    return weather_icons


weather_icons = load_weather_icons()

moon_icons = [
    load_icon(f"moon-phase/phase-{i:02d}.png", MOON_PHASE_BOX, "LA") for i in range(30)
]


def fetch_image(url):
    start = time.monotonic()
    # Send an HTTP GET request to the URL
    with urllib.request.urlopen(url, timeout=15) as response:
        fetch_end = time.monotonic()
        if response.status == 200:
            # Read the response data and decode it as JSON
            image = Image.open(io.BytesIO(response.read()))
            parse_end = time.monotonic()
            print(
                f"Time to fetch image: {fetch_end - start} + {parse_end - fetch_end} = {parse_end - start} sec."
            )
            return image
        else:
            raise Exception(f"request failed with status {response.status}", flush=True)


def fetch_json(url):
    start = time.monotonic()
    # Send an HTTP GET request to the URL
    with urllib.request.urlopen(url, timeout=15) as response:
        fetch_end = time.monotonic()
        if response.status == 200:
            # Read the response data and decode it as JSON
            result_string = response.read().decode("utf-8")
            result = json.loads(result_string)
            parse_end = time.monotonic()
            print(
                f"Time to fetch & parse: {fetch_end - start} + {parse_end - fetch_end} = {parse_end - start} sec."
            )
            return result
        else:
            raise Exception(f"request failed with status {response.status}", flush=True)


class QueryWithCaching:
    def __init__(self, url, cache_time_in_sec):
        self.url = url
        self.cache_time_in_sec = cache_time_in_sec
        self.last_time = None
        self.last_data = None

    def get(self):
        current_time = time.monotonic()
        if (
            self.last_time is None
            or current_time > self.last_time + self.cache_time_in_sec
        ):
            start = time.monotonic()
            # There's evidence that we're running out of memory on the Raspberry
            # Pi 3.  Free all this data before creating the new one.
            self.last_data = None
            print(f"About to fetch at {start - request_start}")
            self.last_data = fetch_json(self.url)
            end_time = time.monotonic()
            print(
                f"Got json, took {end_time - start}, request elapsed {end_time - request_start}"
            )
            self.last_time = current_time
            # print(json.dumps(self.last_data, indent=2))
        return self.last_data


# tomorrow = QueryWithCaching(
#     # the "fields" thing doesn't seem to actually do anything.
#     f"https://api.tomorrow.io/v4/weather/forecast?location={LATITUDE},{LONGITUDE}&apikey={TOMORROW_IO_API_KEY}&fields=precipitationProbability,temperature,sunriseTime,sunsetTime,weatherCodeDay,weatherCodeNight&units=imperial",
#     5 * 60,
# )


# def get_forecast(latitude, longitude):
#     result = tomorrow.get()

#     # tomorrow.io doesn't give you the timezone.
#     timezone = ZoneInfo(TIMEZONE)
#     timelines = result["timelines"]
#     today = timelines["daily"][0]["values"]
#     sunrise = parse_datetime(today["sunriseTime"])
#     sunset = parse_datetime(today["sunsetTime"])

#     isDaytime = sunrise <= datetime.datetime.now(datetime.timezone.utc) <= sunset

#     periods = []
#     for period in timelines["hourly"]:
#         start = parse_datetime(period["time"]).astimezone(timezone)
#         end = start + datetime.timedelta(hours=1)
#         periods.append(
#             Period(
#                 start,
#                 end,
#                 period["values"]["temperature"],
#                 period["values"]["precipitationProbability"] / 100.0,
#             )
#         )

#     now = timelines["minutely"][0]["values"]
#     print(
#         f'{now["precipitationProbability"]=}, {now["freezingRainIntensity"]=}, {now["rainIntensity"]=}, {now["sleetIntensity"]=},  {now["snowIntensity"]=}'
#     )

#     assert "weatherCodeDay" not in today
#     assert "weatherCodeNight" not in today
#     assert today["weatherCodeMin"] == today["weatherCodeMax"]

#     return Forecast(
#         timezone,
#         isDaytime,
#         periods[:24],
#         periods,
#         precipitation_from_weather(today["weatherCodeMin"]),
#         today["windSpeedAvg"],
#         today["cloudCoverAvg"],
#         now["freezingRainIntensity"] > 0
#         or now["rainIntensity"] > 0
#         or now["sleetIntensity"] > 0
#         or now["snowIntensity"] > 0,
#     )


def icon_to_precipitation(icon):
    # https://www.visualcrossing.com/resources/documentation/weather-api/defining-icon-set-in-the-weather-api/
    if icon.startswith("snow"):
        return Precipitation.SNOW
    if icon.startswith("thunder"):
        return Precipitation.THUNDERSTORMS
    if icon.startswith("rain") or icon.startswith("showers"):
        # TODO: distingoush drizzle vs light rain vs rainy.  Maybe use inches/hr
        # of rain?
        return Precipitation.RAINY
    return Precipitation.NONE


visual_crossing_queries = {
    location: QueryWithCaching(
        f"https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline/{location.latitude}%2C{location.longitude}?unitGroup=us&key={CONFIG.visual_crossing_api_key}&contentType=json&iconSet=icons2",
        3.5 * 60,
    )
    for location in CONFIG.locations
}


def get_forecast(location):
    # Visual Crossing documentation:
    # https://www.visualcrossing.com/resources/documentation/weather-api/timeline-weather-api/
    #
    # 1000 free 15-day-forecasts for one location per day.
    # https://www.visualcrossing.com/resources/documentation/weather-data/understanding-and-optimizing-the-visual-crossing-weather-pay-as-you-go-plan/
    result = visual_crossing_queries[location].get()

    timezone = ZoneInfo(result["timezone"])
    # print(timezone)

    today = result["days"][0]
    # Note that these conditions can be up to an hour delayed, as some places
    # only report current conditions once an hour, with a delay of 30 minutes.
    # SMH.
    current = result["currentConditions"]

    # Epoch values are always based around the UTC time zone (sometimes known as GMT).
    #
    now = current["datetimeEpoch"]

    isDayTime = current["sunriseEpoch"] <= now <= current["sunsetEpoch"]

    periods = []
    for day in result["days"]:
        # Note that it takes around an hour after sunset to get dark.
        sunsetEpoch = day["sunsetEpoch"]
        for hour in day["hours"]:
            # Epoch values are always based around the UTC time zone (sometimes known as GMT).
            startEpoch = hour["datetimeEpoch"]
            endEpoch = startEpoch + 60 * 60
            if endEpoch > now:
                start = datetime.datetime.fromtimestamp(startEpoch, timezone)
                end = start + datetime.timedelta(hours=1)

                # The latest anyone would conceivably be awake and star gazing is
                # 5am, and that's also around the earliest sunrise (5:06am) in
                # mid June.  So we can cut off the evening then.  So each day
                # will go from sunset to 5am.
                stargazing = startEpoch > sunsetEpoch or end.hour <= 5
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

    print(f"precip: {current['precip']}, precipprob: {current['precipprob']}")

    return Forecast(
        timezone,
        now,
        isDayTime,
        periods[:24],
        periods,
        icon_to_precipitation(today["icon"]),
        today["windspeed"],
        today["cloudcover"],
        current["precip"] and current["precip"] > 0,
    )


def round_up_to_next_6_hours(input_datetime):
    # Calculate the number of hours to the next multiple of 6
    hours_to_next_6 = (6 - input_datetime.hour % 6) % 6

    timedelta_to_next_6 = timedelta(hours=hours_to_next_6)

    # Round up the input datetime to the next multiple of 6 hours
    rounded_datetime = input_datetime + timedelta_to_next_6
    return rounded_datetime.replace(minute=0, second=0, microsecond=0)


def round_to_next_day(input_datetime):
    truncated = input_datetime.replace(hour=0, minute=0, second=0, microsecond=0)
    if truncated < input_datetime:
        return truncated + timedelta(days=1)
    else:
        return truncated


def plot_graph(periods, image, rect):
    # multiday = False
    multiday = periods[-1].end - periods[0].start > datetime.timedelta(hours=36)
    connected = len(periods) > 48

    min_temp = min(p.temp for p in periods)
    max_temp = max(p.temp for p in periods)

    low_temp = math.floor(min_temp / 5) * 5
    high_temp = math.ceil(max_temp / 5) * 5

    min_time = min(p.start for p in periods).timestamp()
    max_time = max(p.end for p in periods).timestamp()

    draw = ImageDraw.Draw(image)
    font_size = (rect[2] - rect[0]) // 19
    font = ImageFont.truetype(FONT, font_size)

    # This code for adjusting for text size is only approximate, so in practice,
    # when you change font size, you still need to adjust the rect parameter
    # passed into plot_graph().  Oh well.

    y_label_bbox = font.getbbox("99")
    y_label_width = y_label_bbox[2] - y_label_bbox[0]

    x_label_bbox = font.getbbox("Sun")
    x_label_height = x_label_bbox[3] - x_label_bbox[1]

    graph_left = rect[0] + y_label_width
    graph_right = rect[2]
    graph_top = rect[1]
    graph_bottom = rect[3] - x_label_height - GAP_BETWEEN_GRAPH_AND_LABELS

    # Map low_temp to bottom of rect, and high_temp to top.
    def temp_to_y(temp):
        return (temp - low_temp) / (high_temp - low_temp) * (
            graph_top - graph_bottom
        ) + graph_bottom

    def to_x(time):
        time = time.timestamp()
        assert time >= min_time
        assert time <= max_time
        x = (time - min_time) / (max_time - min_time) * (
            graph_right - graph_left
        ) + graph_left
        return x

    #####  Draw the % precipitation polygon.
    precip_polygon = [(graph_left, graph_bottom)]
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
        # prev_y = None
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
            # if prev_y is not None:
            #     draw.line(
            #         (left, y, left, prev_y),
            #         fill=0,
            #         width=1,
            #     )
            # prev_y = y


# This is for tomorrow.io.
def precipitation_from_weather(weather):
    # For tomorrow.io, see
    # https://docs.tomorrow.io/reference/data-layers-weather-codes
    if weather >= 8000:
        return Precipitation.THUNDERSTORMS
    if weather >= 7000:
        # Ice pellets
        return Precipitation.SNOW
    if weather >= 6000:
        # Freezing rain
        return Precipitation.RAINY
    if weather >= 5000:
        return Precipitation.SNOW
    if weather >= 4000:
        return Precipitation.RAINY
    return Precipitation.NONE


def draw_icon(forecast, image, left, top):
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
        DayNight.DAY if forecast.isDaytime else DayNight.NIGHT,
        cloudiness,
        forecast.precipitation,
        windy,
    )
    icon = weather_icons[fname]

    image.paste(icon, box=(ICON_BOX[0], ICON_BOX[1]))


# Paste an image into another image, centering it in the specified box.
def paste_image(image, small_image, box):
    image.paste(
        small_image,
        box=(
            (box[0] + box[2] - small_image.size[0]) // 2,
            (box[1] + box[3] - small_image.size[1]) // 2,
        ),
    )


def get_image(location, is_local=True):
    image = Image.new("L", (800, 480), 255)
    draw = ImageDraw.Draw(image)

    try:
        forecast = get_forecast(location)

    except Exception as e:
        print("***** Got exception in get_image()")
        print(e)
        print(traceback.format_exc(), flush=True)
        forecast = e

    ##### Get the current temperature.  Should probably be made into a function.
    if is_local:
        with local_weather.lock:
            battery_ok = local_weather.battery_ok
            current_temperature = local_weather.temperature
            temperature_elapsed = (
                datetime.datetime.now() - local_weather.time
            ).total_seconds()

    if (not is_local) or (not have_rtl_433):
        current_temperature = (
            0 if isinstance(forecast, Exception) else forecast.periods[0].temp
        )
        temperature_elapsed = 0

    if current_temperature is not None:
        if temperature_elapsed < 5 * 60:
            text = str(round(current_temperature)) + "\N{DEGREE SIGN}"
            current_icon = get_clothing(
                current_temperature,
                isinstance(forecast, Exception) or forecast.is_raining,
            )
        else:
            if temperature_elapsed < 100 * 60:
                text = str(round(temperature_elapsed / 60)) + "m"
            else:
                text = "--"
            current_icon = None
    else:
        current_icon = None
        text = "--"

    ##### Get the afternoon temperature when kids come home from school.
    now = datetime.datetime.now(datetime.timezone.utc).astimezone()
    # This doesn't take into account daylight saving, and so will do the wrong
    # thing between midnight and two am, twice a year.  I can live with that.
    school = now.replace(hour=15, minute=40, second=0, microsecond=0)
    if isinstance(forecast, Exception):
        school_periods = []
    else:
        school_periods = [
            p
            # Skip the first period, since if they're comming home from school
            # within the hour, we want the actual temperature & rain, not forecast.
            for p in forecast.periods[1:]
            if p.start < school and p.end > school
        ]
    school_icon = None
    if school_periods:
        assert len(school_periods) == 1
        school_icon = get_clothing(
            school_periods[0].temp, school_periods[0].precipitation > RAINING_THRESHOLD
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

    if (not is_local) or battery_ok:
        draw.text(
            (
                (TEMPERATURE_BOX[0] + TEMPERATURE_BOX[2]) // 2,
                (TEMPERATURE_BOX[1] + TEMPERATURE_BOX[3]) // 2,
            ),
            text,
            font=font,
            fill=0,
            anchor="mm",
        )

        if not isinstance(forecast, Exception):
            draw_icon(forecast, image, 544, 25)
    else:
        draw.multiline_text(
            (image.size[0] - 128, 89), "Battery\nLow", font=font, fill=0, anchor="mm"
        )
    font = ImageFont.truetype(FONT, 32)
    if isinstance(forecast, Exception):
        if str(forecast) != "HTTP Error 502: Bad Gateway":
            draw.text(
                ((20 + 543) // 2, (25 + 460) // 2),
                str(forecast),
                font=font,
                fill=0,
                anchor="mm",
            )
    else:
        # Plot graph for next 24 hours.
        plot_graph(forecast.periods, image, (20, 25, 543, 215))
        # Plot graph for the coming week.
        plot_graph(forecast.long_range_forecast[: (7 * 24)], image, (20, 270, 543, 460))

        if not is_local:
            now = datetime.datetime.fromtimestamp(forecast.now, forecast.timezone)

            draw.text(
                (
                    (TEMPERATURE_BOX[0] + TEMPERATURE_BOX[2]) // 2,
                    (TEMPERATURE_BOX[1] + TEMPERATURE_BOX[3]) // 2 + 48,
                ),
                now.strftime("%-I:%M%p").lower(),
                font=font,
                fill=0,
                anchor="mm",
            )

    if not is_local:
        draw.text(
            ((TEMPERATURE_BOX[0] + ICON_BOX[2]) // 2, 0),
            location.name,
            font=font,
            fill=0,
            anchor="ma",
        )
    return image


def get_moon_icon(phase):
    # 0 is new moon
    # 15 is full moon
    # 30 would be new moon again, but our max is 29.
    index = int(round(phase * 30))
    print(f"phase {phase} -> {index % 30}")
    return moon_icons[index % 30]


def plot_stargazing(periods, image, rect):
    # Split into group, around noon.

    nights = []
    night = []
    prev_day = periods[0].start

    for period in periods:
        if period.start.hour > 12 and period.start.day != prev_day:
            if night:
                nights.append(night)
            night = []
            prev_day = period.start.day
        night.append(period)
    if night:
        nights.append(night)

    draw = ImageDraw.Draw(image)
    font_size = (rect[2] - rect[0]) // 19
    font = ImageFont.truetype(FONT, font_size)

    # This code for adjusting for text size is only approximate, so in practice,
    # when you change font size, you still need to adjust the rect parameter
    # passed into plot_graph().  Oh well.

    y_label_bbox = font.getbbox("99")
    y_label_width = y_label_bbox[2] - y_label_bbox[0]

    x_label_bbox = font.getbbox("Sun")
    x_label_height = x_label_bbox[3] - x_label_bbox[1]

    graph_left = rect[0] + y_label_width
    graph_right = rect[2]
    graph_top = rect[1]
    graph_bottom = rect[3] - x_label_height - GAP_BETWEEN_GRAPH_AND_LABELS

    #####  Draw the % cloud cover polygons.
    # There are len(night) nights, with len(night) - 1 gaps between them.
    night_width = (
        (graph_right - graph_left) - GAP_BETWEEN_NIGHTS * (len(nights) - 1)
    ) / len(nights)

    end_datetime = max(p.end for p in periods)

    for night_index, night in enumerate(nights):
        print(night)
        min_time = min(p.start for p in night).timestamp()
        max_time = max(p.end for p in night).timestamp()

        night_left = graph_left + (night_width + GAP_BETWEEN_NIGHTS) * night_index
        night_right = night_left + night_width

        def to_x(time):
            time = time.timestamp()
            assert time >= min_time
            assert time <= max_time

            x = (time - min_time) / (max_time - min_time) * (
                night_right - night_left
            ) + night_left
            return x

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
                box=(int(round(x - moon_image.width / 2)), MOON_PHASE_BOX[1]),
                mask=moon_image,
            )

            # Draw text for day of the week
            x = night_left + night_width + GAP_BETWEEN_NIGHTS / 2
            if x < graph_right:
                # noon = midnight + timedelta(hours=12)
                draw.text(
                    (x, graph_bottom + GAP_BETWEEN_GRAPH_AND_LABELS),
                    midnight.strftime("%a"),
                    font=font,
                    fill=0,
                    anchor="ma",
                )


def get_stargazing(location):
    image = Image.new("L", (800, 480), 255)
    draw = ImageDraw.Draw(image)

    try:
        forecast = get_forecast(location)
    except Exception as e:
        print(e, flush=True)
        if str(e) != "HTTP Error 502: Bad Gateway":
            font = ImageFont.truetype(FONT, 32)
            draw.text(
                ((20 + 543) // 2, (25 + 460) // 2),
                str(e),
                font=font,
                fill=0,
                anchor="mm",
            )
        return image

    # This is day (night) based, since we don't care about cloud cover during
    # the day.

    # The latest I could conceivably leave to go stargazing is 8pm, arriving
    # around 10pm.  So, if it's after 8pm today, the first day I'll show will be
    # tomorrow, otherwise today.

    clock_now = datetime.datetime.now()
    periods = forecast.long_range_forecast
    if clock_now.hour >= 20:
        periods = [p for p in periods if p.start.day != clock_now.day]
    periods = periods[: (7 * 24)]

    periods = [period for period in periods if period.stargazing]

    plot_stargazing(periods, image, (20, 50, 800 - 20, 480 - 25))
    return image


def get_unsplash(unsplash):
    query = urllib.parse.quote(unsplash.query)
    rando = fetch_json(
        f"https://api.unsplash.com/photos/random?client_id={unsplash.access_key}&query={query}"
    )
    if LANDSCAPE:
        return rando["urls"]["raw"] + "&w=800&h=480&fit=crop&crop=faces,center&sat=-100"
    else:
        return rando["urls"]["raw"] + "&w=480&h=800&fit=crop&crop=faces,center&sat=-100"


class WeatherHTTPRequestHandler(BaseHTTPRequestHandler):
    pic_num = 0

    def send_image(self, image):
        self.send_response(200)
        self.send_header("Content-type", "image/bmp")
        self.end_headers()
        image.save(self.wfile, format="BMP")

    def do_GET(self):
        global request_start
        request_start = time.monotonic()
        try:
            if self.path == "/weather.bmp":
                print(
                    "***** Someone wants to know whether the weather is wetter.",
                    flush=True,
                )
                for thread in threading.enumerate():
                    print(f"{thread}, native_id={thread.native_id}")
                print(
                    f"Number of active threads in process: {threading.active_count()}"
                )
                image = get_image(CONFIG.home).convert("1")
                print(f"Got image after {time.monotonic() - request_start} sec")
                self.send_image(image)
                print(
                    f"Done sending image response in {time.monotonic() - request_start} sec.",
                    flush=True,
                )
                if False:
                    with open(f"/tmp/weather-{datetime.datetime.now()}.bmp", "wb") as f:
                        image.save(f, format="BMP")
            elif place := PLACE_PAGES.get(self.path):
                print(f"*****  Weather in {place.name}!", flush=True)
                image = get_image(place, False)
                self.send_image(image)

            elif self.path == "/stargazing.bmp" and CONFIG.stargazing:
                print(f"***** Stargazing at {CONFIG.stargazing.name}!", flush=True)
                image = get_stargazing(CONFIG.stargazing)
                self.send_image(image)

            elif self.path == "/wordclock.bmp":
                print("***** What time is it?", flush=True)
                self.send_image(wordclock.render(datetime.datetime.now()))

            elif self.path == "/pics_old.bmp":
                print("***** Dogs are cute", flush=True)
                files = glob.glob("dogs/*.bmp")
                # print(files)

                if WeatherHTTPRequestHandler.pic_num >= len(files):
                    WeatherHTTPRequestHandler.pic_num = 0

                with open(files[WeatherHTTPRequestHandler.pic_num], "rb") as image_file:
                    image_data = image_file.read()

                WeatherHTTPRequestHandler.pic_num += 1

                self.send_response(200)
                self.send_header("Content-type", "image/bmp")
                self.end_headers()
                self.wfile.write(image_data)

            elif self.path == "/pics.bmp" and CONFIG.unsplash:
                print("***** Random pic.", flush=True)

                url = get_unsplash(CONFIG.unsplash)
                print(f"Unsplash url: {url}")

                if LANDSCAPE:
                    self.send_response(307)
                    self.send_header("Location", url)
                    self.end_headers()
                else:
                    # Unfortunately, unsplash has no way to rotate images.  So
                    # we need to fetch it and rotate it ourself.
                    image = fetch_image(url)
                    image = image.transpose(Image.Transpose.ROTATE_90)
                    self.send_image(image)

            else:
                print(
                    "***** Got some other GET request, path = " + self.path, flush=True
                )
                self.send_response(404)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><head><title>Not found.</title></head>")
                self.wfile.write(b"<body><p>Don't hack me go away.</p>")
                self.wfile.write(b"</body></html>")
        except Exception:
            print("***** Got exception!", flush=True)
            self.send_response(500)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><head><title>Python Exception.</title></head>")
            self.wfile.write(b"<body><p>Python code threw an exception.</p>")
            print(traceback.format_exc(), flush=True)
            # self.wfile.write(traceback.format_exc()) Convert to binary?
            self.wfile.write(b"</body></html>")


def run_http_server():
    server_address = ("", 8998)
    print("Launching server.", flush=True)
    httpd = ThreadingHTTPServer(server_address, WeatherHTTPRequestHandler)
    print("Listening.", flush=True)
    httpd.serve_forever()


run_http_server()
