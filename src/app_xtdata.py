# -*- coding: utf-8 -*-

from xtquant import xtdata
import aiohttp, akshare, re, datetime, math, requests, pytz
import pandas as pd
from sanic import Sanic, Blueprint, response
import pandas_market_calendars as mcal

api = Blueprint('xtdata', url_prefix='/api/xtdata')

@api.listener('before_server_start')
async def before_server_start(app, loop):
    '''全局共享session'''
    global session, cn_calendar, cn_tz, a_index_etf, a_index_component, etf_option, hk_index_comonent
    jar = aiohttp.CookieJar(unsafe=True)
    session = aiohttp.ClientSession(cookie_jar=jar, connector=aiohttp.TCPConnector(ssl=False))
    cn_calendar = mcal.get_calendar('SSE')
    cn_tz = pytz.timezone('Asia/Shanghai')

@api.listener('after_server_stop')
async def after_server_stop(app, loop):
    '''关闭session'''
    await session.close()

async def req_json(url):
    async with session.get(url) as resp:
        return await resp.json()

def get_a_index_etf():
    '''
    获取 上证指数、深证成指、创业板指、科创50、上证50、沪深300、中证500、中证1000等主要指数ticker，以及活跃ETFticker
    '''
    indexes = ['000001.SH', '399001.SZ', '399006.SZ', '000688.SH', '000016.SH', '000300.SH', '000905.SH', '000852.SH']
    etf = ["512100.SH", "510050.SH", "510300.SH", "513050.SH", "515790.SH", "563000.SH", "588000.SH", "513180.SH", "513060.SH", "159915.SZ", "512880.SH", "512010.SH", "512660.SH", "159949.SZ", "510500.SH", "512690.SH", "518880.SH", "511260.SH", "512480.SH", "512200.SH", "515030.SH", "511380.SH", "512000.SH", "510330.SH", "513130.SH", "513500.SH", "513100.SH", "512800.SH", "512760.SH", "159920.SZ", "159605.SZ", "159941.SZ", "162411.SZ", "513330.SH", "510900.SH", "513090.SH", "513550.SH"]
    return indexes + etf 

def get_a_index_component():
    '''
    获取沪深300(000300)、中证500(000905)、中证1000(000852)指数成分股
    '''
    hs300 = akshare.index_stock_cons_weight_csindex(symbol="000300")
    hs300['stock'] = hs300.apply(lambda row: row['成分券代码'] + '.' + {'上海证券交易所' :'SH', '深圳证券交易所': 'SZ'}.get(row['交易所']), axis=1)
    csi500 = akshare.index_stock_cons_weight_csindex(symbol="000905")
    csi500['stock'] = csi500.apply(lambda row: row['成分券代码'] + '.' + {'上海证券交易所' :'SH', '深圳证券交易所': 'SZ'}.get(row['交易所']), axis=1)
    csi1000 = akshare.index_stock_cons_weight_csindex(symbol="000852")
    csi1000['stock'] = csi1000.apply(lambda row: row['成分券代码'] + '.' + {'上海证券交易所' :'SH', '深圳证券交易所': 'SZ'}.get(row['交易所']), axis=1)

    hs300_component = hs300.set_index('stock')[['指数代码', '成分券名称', '权重']].to_dict('index')
    csi500_component = csi500.set_index('stock')[['指数代码', '成分券名称', '权重']].to_dict('index')
    csi1000_component = csi1000.set_index('stock')[['指数代码', '成分券名称', '权重']].to_dict('index')

    return hs300_component, csi500_component, csi1000_component

def get_etf_option():
    '''
    获取50ETF、300ETF对应的当月/次月期权ticker
    '''
    select_option = {}

    etf_price = {}
    # 获取ETF行情
    etf_tick = xtdata.get_full_tick(['510300.SH', '510050.SH', '159919.SZ'])
    # 取今日开盘价/昨日收盘价均值
    for code in ['510300.SH', '510050.SH', '159919.SZ']:
        etf_price[code] = (etf_tick[code]['open'] + etf_tick[code]['lastClose']) / 2

    options = xtdata.get_stock_list_in_sector('上证期权') + xtdata.get_stock_list_in_sector('深证期权')
    # 获取主力期权(标的价格附近上下5档,当月/次月)
    for code in options:
        meta = xtdata.get_instrument_detail(code)
        # 期权名称
        name = meta['InstrumentName']
        # 对应的ETF
        etf = re.findall(r'\((\d+)\)', meta['ProductID'])[0] 
        etf = {'510300': '510300.SH', '510050': '510050.SH', '159919': '159919.SZ'}.get(etf)
        # 剩余有效日
        days = (datetime.date(year=int(str(meta['ExpireDate'])[:4]), month=int(str(meta['ExpireDate'])[4:6]), day=int(str(meta['ExpireDate'])[6:8])) - datetime.date.today()).days
        call_put = 'call' if '购' in name else 'put'
        if days < 32:
            if math.fabs(etf_price[etf] - int(name[-4:]) / 1000.0) < 0.2:
                select_option[code] = [etf, call_put, int(name[-4:]), days]
        elif days < 65:
            if math.fabs(etf_price[etf] - int(name[-4:]) / 1000.0) < 0.25:
                select_option[code] = [etf, call_put, int(name[-4:]), days]

    return select_option

def get_a_future_contract():
    '''
    获取中金所、大商所、郑商所、上期所的主要连续合约
    '''
    contract = xtdata.get_stock_list_in_sector('中金所') + xtdata.get_stock_list_in_sector('大商所') + xtdata.get_stock_list_in_sector('郑商所') + xtdata.get_stock_list_in_sector('上期所') 
    market_mapping = {'CZCE': 'ZF', 'DCE': 'DF', 'CFFEX': 'IF', 'SHFE': 'SF'}
    contract_main = [i.split('.')[0] + '.' + market_mapping.get(i.split('.')[1]) for i in contract if re.search(r'[A-Za-z]00\.[A-Z]', i)]
    if 'IM00.IF' not in contract_main:
        contract_main.append('IM00.IF')
    return contract_main

def get_a_cffex_contract():
    '''
    获取中金所股指期货和期权合约(上证50、沪深300[期权IO]、中证500、中证1000[期权MO])
    交割日期：每月第三个周五，遇节假日顺延
    '''
    trade_month = []
    today = datetime.date.today()
    this_month = datetime.date(today.year, today.month, 1)
    next_month1 = this_month + datetime.timedelta(days=31)
    next_month2 = this_month + datetime.timedelta(days=62)

    cnt = 0
    temp_date = None
    for i in pd.date_range(this_month, next_month1, freq='D'):
        if i.weekday() == 4:
            cnt += 1
        if cnt == 3:
            temp_date = i
            break

    month0_reverso_date = cn_calendar.schedule(start_date=temp_date, end_date=next_month1, tz=cn_tz).index.tolist()[0].date()
    if today > month0_reverso_date:
        # 本月交割日期之后，选择次月、次次月
        trade_month = ['{}{}'.format(next_month1.year % 100, str(next_month1.month).zfill(2)), '{}{}'.format(next_month2.year % 100, str(next_month2.month).zfill(2))]
    else:
        trade_month = ['{}{}'.format(this_month.year % 100, str(this_month.month).zfill(2)), '{}{}'.format(next_month1.year % 100, str(next_month1.month).zfill(2))]

    future_main_contract = ['{}{}.IF'.format(i, j) for i in ['IH', 'IF', 'IC', 'IM'] for j in trade_month]
    return future_main_contract, trade_month

def get_global_future_contract():
    '''
    外盘期货市场主要标的，包含汇率、利率、商品以及股指
    '''
    forex = ['DXY.OTC', 'EURUSD.OTC', 'GBPUSD.OTC', 'USDJPY.OTC', 'USDRUB.OTC', 'USDCNH.OTC', 'USDHKD.OTC']
    interest = ['US10YR.OTC', 'DE10YR.OTC', 'UK10YR.OTC', 'CN10YR.OTC', 'JP10YR.OTC', 'US5YR.OTC', 'US2YR.OTC', 'US1YR.OTC', 'US30YR.OTC', 'FR10YR.OTC', 'CN5YR.OTC', 'CN2YR.OTC', 'CN1YR.OTC', 'CN7YR.OTC']
    commodity = ['USHG.OTC', 'UKAH.OTC', 'UKCA.OTC', 'UKNI.OTC', 'UKPB.OTC', 'UKZS.OTC', 'UKSN.OTC', 'USZC.OTC', 'USZW.OTC', 'USYO.OTC', 'USZS.OTC', 'USLHC.OTC', 'UKOIL.OTC', 'USCL.OTC', 'USNG.OTC', 'XAUUSD.OTC', 'USGC.OTC', 'XAGUSD.OTC', 'USSI.OTC', 'AUTD.SGE', 'AGTD.SGE', 'PT9995.SGE', 'USPL.OTC', 'USPA.OTC']
    index = ["US500F.OTC", "VIXF.OTC", "US30F.OTC", "USTEC100F.OTC", "JP225F.OTC", "EU50F.OTC", "DE30F.OTC", "FR40F.OTC", "ES35F.OTC", "AU200F.OTC", "STOXX50F.OTC"]
    return forex + interest + commodity + index

def get_hk_index_comonent():
    '''
    获取恒生指数、恒生科技指数的成分股
    '''
    url = 'https://quotes.sina.cn/hq/api/openapi.php/HK_StockRankService.getHkStockList?page=1&num=100&symbol={}&asc=0&sort=changepercent&type={}'
    headers = {"user-agent": "sinafinance__6.4.0__iOS__248f2d8bf77fb1696a52f1bd4a55c1a256e54711__15.6__iPhone 11 Pro", "Host": "quotes.sina.cn", "accept-language": "zh-CN,zh-Hans;q=0.9"}

    component = {"HSI": {}, "HSTECH": {}}
    for index in ["HSI", "HSTECH"]:
        data = requests.get(url.format(index, index), headers=headers)
        try:
            data = data.json()['result']['data']['data']
            for item in data:
                component[index][item['symbol'] + '.HK'] = [index, item['name'], float(item['weight'])]
        except:
            pass
    return component["HSI"], component["HSTECH"]


if __name__ == '__main__':
    app = Sanic(name='xtquant')
    app.config.RESPONSE_TIMEOUT = 600000
    app.config.REQUEST_TIMEOUT = 600000
    app.config.KEEP_ALIVE_TIMEOUT = 600
    app.blueprint(api)
    app.run(host='127.0.0.1', port=7800, workers=1, auto_reload=True, debug=False)