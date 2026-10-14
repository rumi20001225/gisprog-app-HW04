"""HW5 參考解答：在 HW4 的 App 加上 leafmap 地圖（ipyleaflet 後端）。

僅供教師批改與示範使用，不發給學生。放進 template repo 取代 app.py，
並在 requirements.txt 加上 leafmap==0.63.1 即可執行。
版面為響應式：螢幕寬 960 px 以上並排，手機上下排列。
底圖為內政部國土測繪中心的臺灣通用電子地圖（WMTS）。
在終端機執行：`solara run app.py --no-open`。
"""

import threading
from pathlib import Path

import ipyleaflet  # leafmap 已一併安裝，不用另外寫進 requirements.txt
import leafmap.leafmap as leafmap  # ipyleaflet 後端：Solara 原生支援的 widget
import pandas as pd
import plotly.express as px
import solara

DATA_PATH = Path(__file__).parent / "data" / "youbike_sample.csv"

df = pd.read_csv(DATA_PATH, dtype={"sno": str, "act": str})
df = df[df["act"] == "1"]  # 只看營運中的站

時段們 = sorted(df["時段"].unique())
行政區們 = sorted(df["sarea"].unique())

門檻 = solara.reactive(0)
時段 = solara.reactive(時段們[0])
行政區 = solara.reactive("大安區")

# Solara 會同時服務多個使用者，各自的畫面可能在不同執行緒同時更新。
# 畫 Plotly 圖表時加鎖，一次只讓一個執行緒畫，避免互相干擾。
畫圖鎖 = threading.Lock()

# 臺灣通用電子地圖（內政部國土測繪中心 WMTS，GoogleMapsCompatible 圖磚）
底圖網址 = "https://wmts.nlsc.gov.tw/wmts/EMAP/default/GoogleMapsCompatible/{z}/{y}/{x}"
底圖出處 = "臺灣通用電子地圖 © 內政部國土測繪中心"

# 可借車數分級：(下限, 上限, 圖例文字, 顏色)。顏色取自 viridis，色盲也分得出深淺。
分級 = [
    (0, 0, "0 輛（空站）", "#440154"),
    (1, 3, "1–3 輛", "#31688e"),
    (4, 9, "4–9 輛", "#35b779"),
    (10, 999, "10 輛以上", "#fde725"),
]


def 各區空站比例(資料, 門檻值):
    """計算各區的站數、空站數與空站比例（可借車 <= 門檻值 算空站）。"""
    資料 = 資料.assign(空站=資料["available_rent_bikes"] <= 門檻值)
    表 = 資料.groupby("sarea").agg(站數=("sno", "size"), 空站數=("空站", "sum"))
    表["空站比例"] = (表["空站數"] / 表["站數"]).round(3)
    return 表.sort_values("空站比例", ascending=False).reset_index()


def 單區各時段(資料, 區, 門檻值):
    """計算一個行政區在各時段的站數、可借車總數與空站比例。"""
    資料 = 資料[資料["sarea"] == 區].assign(空站=資料["available_rent_bikes"] <= 門檻值)
    表 = 資料.groupby("時段").agg(
        站數=("sno", "size"),
        可借車總數=("available_rent_bikes", "sum"),
        空站數=("空站", "sum"),
    )
    表["空站比例"] = (表["空站數"] / 表["站數"]).round(3)
    return 表.reset_index()


def 轉成GeoJSON(資料):
    """把站點表格轉成 GeoJSON（就是 W2 學過的 dict 與 list）。注意座標順序是 [經度, 緯度]。"""
    features = []
    for _, 列 in 資料.iterrows():
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [列["longitude"], 列["latitude"]]},
                "properties": {
                    "站名": 列["sna"].replace("YouBike2.0_", ""),
                    "可借車": int(列["available_rent_bikes"]),
                    "可還空位": int(列["available_return_bikes"]),
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def 依可借車數著色(feature):
    """leafmap 對每個站點呼叫一次，回傳這個點的顏色。"""
    車數 = feature["properties"]["可借車"]
    for 下限, 上限, _, 顏色 in 分級:
        if 下限 <= 車數 <= 上限:
            return {"fillColor": 顏色}
    return {"fillColor": "#999999"}  # 不在任何一級（理論上不會發生）


@solara.component
def 站點地圖(區, 時):
    """選定行政區與時段的站點地圖。"""

    def 建立地圖():
        站點 = df[(df["sarea"] == 區) & (df["時段"] == 時)]
        m = leafmap.Map(
            center=[站點["latitude"].mean(), 站點["longitude"].mean()],
            zoom=14,
            height="450px",
            # 用臺灣通用電子地圖取代預設的 OpenStreetMap 底圖。
            # 一定要給 name：leafmap 建地圖時會找「有名稱的圖層」，一個都沒有就會出錯。
            basemap=ipyleaflet.TileLayer(
                url=底圖網址, attribution=底圖出處, max_zoom=19, name="臺灣通用電子地圖"
            ),
            draw_control=False,
            measure_control=False,
            toolbar_control=False,
            search_control=False,
        )
        m.layers[0].name = "臺灣通用電子地圖"  # leafmap 會把第一個圖層命名為 OpenStreetMap，改回正確名稱
        m.add_geojson(
            轉成GeoJSON(站點),
            layer_name="YouBike 站點",
            point_style={"radius": 6, "color": "#333333", "weight": 1, "fillOpacity": 0.9},
            style_callback=依可借車數著色,
            info_mode="on_click",  # 點站點，右下角顯示站名與可借車數
        )
        m.add_legend(
            title="可借車數",
            legend_dict={文字: 顏色.lstrip("#") for _, _, 文字, 顏色 in 分級},
        )
        return m

    # 只有行政區或時段改變時才重建地圖；拖門檻滑桿不會重建。
    m = solara.use_memo(建立地圖, dependencies=[區, 時])
    solara.display(m)


@solara.component
def Page():
    solara.Title("YouBike 空站觀察")
    solara.Markdown("# 臺北 YouBike 各區空站比例")

    # 響應式版面：寬度 12 是整列。手機上每個元件佔滿一列、上下排；
    # 螢幕寬度 960 px 以上（medium）才改成並排。
    with solara.ColumnsResponsive(12, medium=[4, 4, 4]):
        solara.SliderInt("空站門檻：可借車 ≤", value=門檻, min=0, max=5)
        solara.ToggleButtonsSingle(value=時段, values=時段們)
        solara.Select(label="行政區", value=行政區, values=行政區們)

    # 新增：單一行政區的地圖與各時段變化
    solara.Markdown(f"## {行政區.value}")
    with solara.ColumnsResponsive(12, medium=[7, 5]):
        with solara.Column():
            solara.Markdown(f"**{時段.value} 的站點**（點擊站點看站名與可借車數）")
            站點地圖(行政區.value, 時段.value)
        with solara.Column():
            區表 = 單區各時段(df, 行政區.value, 門檻.value)
            # 圖表標題放在 Markdown：手機上會自動換行；Plotly 的標題不會換行，會被切掉。
            solara.Markdown(f"**各時段空站比例**（可借車 ≤ {門檻.value}，只算營運中的站）")
            with 畫圖鎖:
                區圖 = px.bar(區表, x="時段", y="空站比例")
                區圖.update_layout(yaxis_tickformat=".0%", height=300, margin={"l": 10, "r": 10, "t": 10, "b": 10})
            solara.FigurePlotly(區圖)
            solara.DataFrame(區表)

    # 原本 template 的全市比較
    solara.Markdown("## 各區比較")
    當時 = df[df["時段"] == 時段.value]
    表 = 各區空站比例(當時, 門檻.value)
    with solara.ColumnsResponsive(12, medium=[7, 5]):
        with solara.Column():
            solara.Markdown(f"**{時段.value}，可借車 ≤ {門檻.value} 算空站**（只算營運中的站）")
            with 畫圖鎖:
                圖 = px.bar(
                    表,
                    x="空站比例",
                    y="sarea",
                    orientation="h",
                    labels={"sarea": "", "空站比例": "空站比例"},
                )
                # 每區給 30 px 高度，行政區名稱才不會被 Plotly 自動隔行省略；換成區數更多的縣市也適用。
                圖.update_layout(
                    yaxis={"categoryorder": "total ascending"},
                    xaxis_tickformat=".0%",
                    height=60 + 30 * len(表),
                    margin={"l": 10, "r": 10, "t": 10, "b": 10},
                )
            solara.FigurePlotly(圖)
        solara.DataFrame(表)

    solara.Markdown(
        "資料來源：臺北市 YouBike 2.0 即時資料（臺北市資料大平臺），"
        "依政府資料開放授權條款第 1 版使用。"
        "資料時間：2026-09-25（五）12:28、17:58、23:28。"
        "底圖：臺灣通用電子地圖，© 內政部國土測繪中心。"
    )
