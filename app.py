import requests
from bs4 import BeautifulSoup
import pandas as pd
import locale
from datetime import datetime
import mibian
import boto3

locale.setlocale(locale.LC_ALL, 'es_ES.UTF-8')


def get_data():
    response = requests.get('https://www.meff.es/esp/Derivados-Financieros/Ficha/FIEM_MiniIbex_35')

    if response.status_code == 200:
        soup = BeautifulSoup(response.text, 'html.parser')
        if soup is not None:
            future = soup.find('table', {'id': 'Contenido_Contenido_tblFuturos'})
            df_future = pd.read_html(str(future), decimal=',', thousands='.')[0]
            df_future.columns = df_future.columns.get_level_values(0)
            df_future = df_future.iloc[:-1, [0, -1]]
            df_future.index = [i.replace('.', '') for i in df_future.iloc[:, 0].values.tolist()]
            df_future = df_future.iloc[:, 1]
            df_future.index = pd.to_datetime(df_future.index, format='%d %b %Y')
            df_future.name = 'price'


            option = soup.find('table', {'id': 'tblOpciones'})
            indexes = option.find_all('tbody')[0].find_all('tr')[:-2]
            indexes = [i.attrs['data-tipo'] for i in indexes]

            df_option = pd.read_html(str(option), decimal=',', thousands='.')[0]
            df_option.columns = df_option.columns.get_level_values(0)
            list_option = df_option.iloc[:-2, [0, -1]].values[:].tolist()

            df_option = pd.DataFrame([[ind[1:2], ind[2:3], datetime.strptime(ind[3:], '%Y%m%d'), float(opt[0]), float(opt[1])] for ind, opt in zip(indexes, list_option) if opt[1] != '-'], columns=['call_put', 'type', 'date', 'strike', 'price'])
            df_option.index = df_option.iloc[:, 2].values
            df_option = df_option.iloc[:, [0, 1, 3, 4]]
            df_option = df_option[df_option.type == 'E']

            return df_future, df_option


def implied_volatility(df_option, future_price):
    """
    Calculate implied volatility for a given future price, strike, expiry and price.
    """
    if df_option.call_put == 'C':
        c = mibian.BS([future_price, df_option.strike, 0, (df_option.name-datetime.today()).days], callPrice=df_option.price)
        return c.impliedVolatility
    elif df_option.call_put == 'P':
        p = mibian.BS([future_price, df_option.strike, 0, (df_option.name-datetime.today()).days], putPrice=df_option.price)
        return p.impliedVolatility


def handler(event, context):
    print(event)
    
    df_future, df_option = get_data()

    df_option['implied_volatility'] = df_option.apply(lambda row: implied_volatility(df_option=row, future_price=df_future.iloc[0]), axis=1)
    df_option = df_option.reset_index(level=0)
    df_option = df_option.rename(columns={'index': 'expiration_date'})
    df_option.expiration_date = df_option.expiration_date.apply(lambda x: datetime.strftime(x, '%Y-%m-%d'))
    df_option.strike = df_option.strike.apply(lambda x: str(x))
    df_option.price = df_option.price.apply(lambda x: str(x))
    df_option.implied_volatility = df_option.implied_volatility.apply(lambda x: str(x))    

    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table('MINI_IBEX_VOL')

    record = {'DATE':datetime.today().strftime('%Y-%m-%d'), 'DATA':df_option.to_dict(orient='records')}

    response = table.put_item(
        Item=record
    )

    return response['ResponseMetadata']['HTTPStatusCode']