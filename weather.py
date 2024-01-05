import urllib.request
import json
from datetime import timedelta
import datetime
import time
from PIL import Image, ImageDraw, ImageFont
import math
import sys
from zoneinfo import ZoneInfo
from http.server import HTTPServer, BaseHTTPRequestHandler
from enum import Enum
import os
import shutil
import subprocess
import threading
import time
import argparse
import signal
import traceback


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
TIMEZONE = "America/New_York"

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

# If using rtl_433 to read a physical, outdoor temperature sensor, only listen
# to the model and channel specified here.  ID changes when you change the
# batteries on the sensor, so to support ID, I'd need some kind of pairing
# process.  Currently, mine is the only LaCrosse sensor that I receive, so model
# and channel is more than enough.
RTL_433_MODEL = "LaCrosse-TX141THBv2"
RTL_433_CHANNEL = 0


def print_stack(sig, frame):
    print("**********  In signal handler, printing stack frame.  **********")
    print("".join(traceback.format_stack(frame)))
    print("**********  Exiting signal handler.  **********", flush=True)


signal.signal(signal.SIGUSR1, print_stack)

# Set current directory to the directory containing this script.
os.chdir(os.path.dirname(os.path.abspath(sys.argv[0])))


def parse_datetime(string):
    return datetime.datetime.fromisoformat(string.replace("Z", "+00:00"))


TOMORROW_IO_API_KEY = os.getenv("TOMORROW_IO_API_KEY")
if not TOMORROW_IO_API_KEY:
    print(
        "Please supply tomorrow.io API key in the environment variable TOMORROW_IO_API_KEY",
        file=sys.stderr,
    )
    sys.exit(1)


parser = argparse.ArgumentParser(
    prog="weather",
    description="Serve weather dashboard for invisible-computer e-ink display",
)
parser.add_argument("latitude", type=float)
parser.add_argument("longitude", type=float)
args = parser.parse_args()

LATITUDE = args.latitude
LONGITUDE = args.longitude


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
        print("Entered LocalWeather.set()", flush=True)
        with self.lock:
            self.time = time
            self.temperature = temperature
            self.humidity = humidity
            self.battery_ok = battery_ok
        print("Exiting LocalWeather.set()", flush=True)


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
    def __init__(self, start, end, temp, precipitation):
        self.start = start
        self.end = end
        self.temp = temp
        self.precipitation = precipitation
        self.mid = self.start + (self.end - self.start) / 2

    def __repr__(self):
        return f"{self.start} to {self.end} temp: {self.temp}"


class Forecast:
    def __init__(
        self,
        timezone,
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
        self.isDaytime = isDaytime
        self.periods = periods
        self.long_range_forecast = long_range_forecast
        self.precipitation = precipitation
        self.wind_speed = wind_speed
        self.clouds = clouds
        self.is_raining = is_raining


def load_icon(fname, box):
    return scale_to_fit(Image.open(fname).convert("L"), box)


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


def fetch_json(url):
    # Send an HTTP GET request to the URL
    with urllib.request.urlopen(url, timeout=15) as response:
        if response.status == 200:
            # Read the response data and decode it as JSON
            return json.loads(response.read().decode("utf-8"))
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
            self.last_data = fetch_json(self.url)
            self.last_time = current_time
        return self.last_data


tomorrow = QueryWithCaching(
    f"https://api.tomorrow.io/v4/weather/forecast?location={LATITUDE},{LONGITUDE}&apikey={TOMORROW_IO_API_KEY}&fields=precipitationProbability,temperature,sunriseTime,sunsetTime,weatherCodeDay,weatherCodeNight&units=imperial",
    5 * 60,
)


def get_forecast(latitude, longitude):
    # the "fields" thing doesn't seem to actually do anything.
    result = tomorrow.get()

    # tomorrow.io doesn't give you the timezone.
    timezone = ZoneInfo(TIMEZONE)
    timelines = result["timelines"]
    today = timelines["daily"][0]["values"]
    sunrise = parse_datetime(today["sunriseTime"])
    sunset = parse_datetime(today["sunsetTime"])

    isDaytime = sunrise <= datetime.datetime.now(datetime.timezone.utc) <= sunset

    periods = []
    for period in timelines["hourly"]:
        start = parse_datetime(period["time"]).astimezone(timezone)
        end = start + datetime.timedelta(hours=1)
        periods.append(
            Period(
                start,
                end,
                period["values"]["temperature"],
                period["values"]["precipitationProbability"] / 100.0,
            )
        )

    now = timelines["minutely"][0]["values"]
    print(
        f'{now["precipitationProbability"]=}, {now["freezingRainIntensity"]=}, {now["rainIntensity"]=}, {now["sleetIntensity"]=},  {now["snowIntensity"]=}'
    )

    assert "weatherCodeDay" not in today
    assert "weatherCodeNight" not in today
    assert today["weatherCodeMin"] == today["weatherCodeMax"]

    return Forecast(
        timezone,
        isDaytime,
        periods[:24],
        periods,
        precipitation_from_weather(today["weatherCodeMin"]),
        today["windSpeedAvg"],
        today["cloudCoverAvg"],
        now["freezingRainIntensity"] > 0
        or now["rainIntensity"] > 0
        or now["sleetIntensity"] > 0
        or now["snowIntensity"] > 0,
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
    font_size = (rect[3] - rect[1]) // 7
    font = ImageFont.truetype("Pillow/Tests/fonts/DejaVuSans.ttf", font_size)

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


def get_image():
    image = Image.new("L", (800, 480), 255)
    draw = ImageDraw.Draw(image)

    try:
        forecast = get_forecast(LATITUDE, LONGITUDE)

    except Exception as e:
        print(e, flush=True)
        forecast = e

    ##### Get the current temperature.  Should probably be made into a function.
    print("About to grab local_weather.lock", flush=True)
    with local_weather.lock:
        battery_ok = local_weather.battery_ok
        current_temperature = local_weather.temperature
        temperature_elapsed = (
            datetime.datetime.now() - local_weather.time
        ).total_seconds()
    print("Released local_weather.lock", flush=True)

    if not have_rtl_433:
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

    font = ImageFont.truetype("Pillow/Tests/fonts/DejaVuSans.ttf", 64)

    if battery_ok:
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
    if isinstance(forecast, Exception):
        if str(forecast) != "HTTP Error 502: Bad Gateway":
            font = ImageFont.truetype("Pillow/Tests/fonts/DejaVuSans.ttf", 32)
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
        plot_graph(forecast.long_range_forecast, image, (20, 270, 543, 460))

    return image


class WeatherHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        start = time.monotonic()
        try:
            if self.path == "/weather.bmp":
                print(
                    "Someone wants to know whether the weather is wetter.", flush=True
                )
                image = get_image().convert("1")
                self.send_response(200)
                self.send_header("Content-type", "image/bmp")
                self.end_headers()
                # image = Image.open("/tmp/bad.bmp")
                # image.save(self.wfile, format="BMP")

                image.save(self.wfile, format="BMP")

                print(
                    f"Done sending image response in {time.monotonic() - start} sec.",
                    flush=True,
                )
                if False:
                    with open(f"/tmp/weather-{datetime.datetime.now()}.bmp", "wb") as f:
                        image.save(f, format="BMP")
            else:
                print("Got some other GET request.", flush=True)
                self.send_response(404)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><head><title>Not found.</title></head>")
                self.wfile.write(b"<body><p>Don't hack me go away.</p>")
                self.wfile.write(b"</body></html>")
        except Exception:
            print("Got exception!", flush=True)
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
    httpd = HTTPServer(server_address, WeatherHTTPRequestHandler)
    print("Listening.", flush=True)
    httpd.serve_forever()


run_http_server()
