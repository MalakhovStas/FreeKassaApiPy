from dataclasses import dataclass, field
from typing import Dict
from datetime import datetime
import requests
import sqlite3
import hashlib


class Database:
    def __init__(self, path_db):
        self.database = sqlite3.connect(path_db)
        self.cursor = self.database.cursor()
        self.__create_tables()

    def __create_tables(self) -> None:
        with self.database:
            self.cursor.execute("""CREATE TABLE IF NOT EXISTS kassa(
                                    nonce INTEGER PRIMARY KEY NOT NULL,
                                    url TEXT,
                                    body_request  TEXT,
                                    status TEXT,
                                    body_response TEXT,
                                    date_time TIMESTAMP)""")

            self.cursor.execute("""CREATE TABLE IF NOT EXISTS wallet(
                                    num_request INTEGER PRIMARY KEY NOT NULL,
                                    body_request  TEXT,
                                    status TEXT,
                                    body_response TEXT,
                                    date_time TIMESTAMP)""")
            self.database.commit()

    def select_max_nonce(self):
        with self.database:
            self.cursor.execute("SELECT nonce FROM kassa WHERE nonce=(select max(nonce) from kassa)")
            result = self.cursor.fetchone()
        return result

    def insert_request_kassa(self, nonce, url, body_request, status, body_response):
        with self.database:
            self.cursor.execute("INSERT INTO kassa(nonce, url, body_request, status, body_response, date_time) "
                                "VALUES  (?, ?, ?, ?, ?, ?)",
                                (nonce, url, body_request, status, body_response, datetime.now()))
            self.database.commit()

    def insert_request_wallet(self, body_request, status, body_response):
        with self.database:
            self.cursor.execute("INSERT INTO wallet(body_request, status, body_response, date_time) "
                                "VALUES  (?, ?, ?, ?)",
                                (body_request, status, body_response, datetime.now()))
            self.database.commit()


class FreeKassaApi:

    def __init__(self, merchant_id: int, first_secret: str, second_secret: str,
                 freekassa_api_key: str, base_url: str, db: Database) -> None:

        self.merchant_id = merchant_id
        self.first_secret = first_secret
        self.second_secret = second_secret
        self.freekassa_api_key = freekassa_api_key
        self.base_url = base_url
        self.db = db

    def make_body_request(self, data: Dict | None = None) -> Dict:
        nonce = self.db.select_max_nonce()[0] + 1 if self.db.select_max_nonce() else 1

        if data:
            data.update({'nonce': nonce, 'shopId': self.merchant_id})
        else:
            data: Dict = {'nonce': nonce, 'shopId': self.merchant_id}

        body = dict(sorted(data.items()))
        signature = self.make_signature(body=body)
        body.update({'signature': signature})
        # print(body)
        return body

    def make_signature(self, body: Dict, sep: str = '|') -> str:
        """Подпись запросов"""
        line = f'{sep}'.join(map(str, body.values())) + f'{sep}{self.freekassa_api_key}'
        # print(line)
        return hashlib.md5(line.encode('utf-8')).hexdigest()

    def get_(self, url_method, data: Dict | None = None) -> Dict:
        url = self.base_url + url_method
        body = self.make_body_request(data=data if data else None)

        try:
            response = requests.post(url=url, json=body)

        except Exception as exc:
            response = {"Exception": exc}
            self.db.insert_request_kassa(nonce=body['nonce'], url=url, body_request=str(body),
                                         status=exc.__class__, body_response=f'Exception: {exc}')
        else:
            self.db.insert_request_kassa(nonce=body['nonce'], url=url, body_request=str(body),
                                         status=response.status_code, body_response=response.text)

        print(response.request.body)
        print(response.status_code)
        print(response.text)
        return response.json()

    def thisform(self):
        """Настройка формы оплаты"""
        pass

    def this(self):
        """Оповещение о платеже"""
        pass

    #TODO Подтверждение заявки
    # Если Вы хотите быть уверены, что подтверждение на URL оповещения дошло успешно и обработано верно,
    # добавьте в скрипт URL оповещения вывод слова YES и обратитесь в техподдержку для включения функции
    # проверки. После этого наш сервер будет передавать информацию о платеже на ваш URL оповещения до тех
    # пор, пока не получит ответ YES.

    #TODO Проверка IP
    # Рекомендуем так же проверять IP сервера отправляющего Вам информацию,
    # наши IP - 168.119.157.136, 168.119.60.227, 138.201.88.124, 178.154.197.79


    def signatures_payment_form(self, amount: float, currency: str, orderId: int):
        """Формирование подписи в платежной форме"""
        line = ':'.join(map(str, [self.merchant_id, amount, self.first_secret, currency, orderId]))
        # print(line)
        return hashlib.md5(line.encode('utf-8')).hexdigest()

    def signatures_notification_script(self, amount: float, orderId: int) -> str:
        """Формирование подписи в скрипте оповещения"""
        line = ':'.join(map(str, [self.merchant_id, amount, self.second_secret, orderId]))
        # print(line)
        return hashlib.md5(line.encode('utf-8')).hexdigest()

    def get_order_list(self, **kwargs) -> Dict:
        """Получить список заказов
        необязательные
        :param orderId (int) - Номер заказа Freekassa, Example: orderId=123456789
        :param paymentId (str) - Номер заказа в Вашем магазине, Example: paymentId=987654321
        :param orderStatus (int) - Статус заказа, Example: orderStatus=1
        :param dateFrom (str) - Дата с, Example: dateFrom=2021-01-01 13:45:21
        :param dateTo (str) - Дата по, Example: dateTo=2021-01-02 13:45:21
        :param page (int) - Страница

        Статусы заказов
        0 - Новый
        1 - Оплачен
        8 - Ошибка
        9 - Отмена
        """
        params = {}

        for key, value in kwargs.items():
            params.update({key: value})

        return self.get_('orders', data=params)

    def create_order_get_payment_link(self, i: int, email: str, ip: str, amount: float, currency: str, **kwargs) -> Dict:
        """Создать заказ и получить ссылку на оплату
        обязательные:
        :param i: (int) - ID платежной системы, Example: i=6
        :param email: (str) - Email покупателя, Example: email=user@site.ru
        :param ip: (str) - IP покупателя, Example: ip=85.8.8.8
        :param amount: (float) - Сумма оплаты Example: amount=100.23
        :param currency: (str) - Валюта оплаты Example: currency=RUB
        необязательные:
        :param paymentId: (str) - Номер заказа в Вашем магазине, Example: paymentId=987654321
        :param tel: (str) - Телефон плательщика, требуется в некоторых способах оплат, Example: tel=+79261231212
        :param success_url: (str) - Переопределение урла успеха (для включения данного параметра обратитесь в поддержку)
               Example: success_url=https://site.ru/success
        :param failure_url: (str) - Переопределение урла ошибки (для включения данного параметра обратитесь в поддержку)
               Example: failure_url=https://site.ru/error
        :param notification_url: (str) - Переопределение урла уведомлений (для включения данного параметра обратитесь в
               поддержку), Example: notification_url=https://site.ru/notify
        """
        params = {
            'i': i,
            'email': email,
            'ip': ip,
            'amount': amount,
            'currency': currency,
            }

        for key, value in kwargs.items():
            params.update({key: value})

        return self.get_('orders/create', data=params)

    def get_list_payouts(self, **kwargs) -> Dict:
        """Список выплат
        необязательные
        :param orderId: (int) - Номер заказа Freekassa, Example: orderId=123456789
        :param paymentId: (str) - Номер заказа в Вашем магазине, Example: paymentId=987654321
        :param orderStatus: (int) - Статус заказа, Example: orderStatus=1
        :param dateFrom: (str) - Дата с, Example: dateFrom=2021-01-01 13:45:21
        :param dateTo: (str) - Дата по, Example: dateTo=2021-01-02 13:45:21
        :param page: (int) - Страница
        """
        params = {}

        for key, value in kwargs.items():
            params.update({key: value})

        return self.get_('withdrawals', data=params)

    def create_payout(self, i: int, account: int, amount: float, currency: str, paymentId: str | None = None) -> Dict:
        """Создать выплату
        :param i: (int) - ID платежной системы Example: i=6
        :param account: (str) - Кошелек для зачисления средств (при выплате на FKWallet вывод осуществляется только
                         на свой аккаунт) Example: account=5500000000000004
        :param amount: (float) - Сумма оплаты Example: amount=100.23
        :param currency: (str) - Валюта оплаты Example: currency=RUB
        :param paymentId: (str | None) - Номер заказа в Вашем магазине Example: paymentId=987654321

        """
        params = {
            'i': i,
            'account': account,
            'amount': amount,
            'currency': currency,
            }
        if paymentId:
            params.update({'paymentId': paymentId})

        return self.get_('withdrawals/create', data=params)

    def get_balance(self) -> Dict:
        """Получение баланса"""
        return self.get_('balance')

    def get_list_available_payment_systems(self) -> Dict:
        """Получение списка доступных платежных систем"""
        return self.get_('currencies')

    def checking_availability_payment_system(self) -> Dict:
        """Проверка доступности платежной системы для оплаты"""
        return self.get_(f'currencies/{self.merchant_id}/status')

    def get_list_available_payment_systems_withdrawal(self) -> Dict:
        """Получение списка доступных платежных систем для вывода"""
        return self.get_('withdrawals/currencies')

    def get_shops(self) -> Dict:
        """Получение списка Ваших магазинов"""
        return self.get_('shops')


class FKWalletApi:

    def __init__(self, wallet_id: str, fkwallet_api_key: str, base_url: str, db: Database):
        self.wallet_id = wallet_id
        self.fkwallet_api_key = fkwallet_api_key
        self.base_url = base_url
        self.db = db

    def make_signature(self, body: Dict, sep: str = '') -> str:
        """Подпись запросов"""
        line = f'{sep}'.join(map(str, body.values())) + f'{sep}{self.fkwallet_api_key}'
        # print(line)
        return hashlib.md5(line.encode('utf-8')).hexdigest()

    def make_body_request(self, data: Dict | None = None) -> Dict:
        if data:
            data.update({'wallet_id': self.wallet_id})
        else:
            data: Dict = {'wallet_id': self.wallet_id}

        # body = dict(sorted(data.items()))
        body = data
        signature = self.make_signature(body=data)
        body.update({'sign': signature})
        # print(body)
        return body

    def __get(self, action: str, data: Dict | None = None) -> Dict | None:
        body = self.make_body_request(data=data if data else None)
        body.update({'action': action})
        print(body)
        try:
            response = requests.post(url=self.base_url, data=body)

        except Exception as exc:
            response = {"Exception": exc}
            self.db.insert_request_wallet(body_request=str(body), status=exc.__class__,
                                          body_response=f'Exception: {exc}')
        else:
            self.db.insert_request_wallet(body_request=str(body), status=response.status_code,
                                          body_response=response.text)

        # print(response.request.body)
        # print(response.status_code)
        print(response.json())
        return response.json()

    def get_balance(self):
        """Получение баланса кошелька"""
        return self.__get(action='get_balance')

    #TODO
    def withdrawing(self):
        """Вывод средств из кошелька"""
        pass

    def list_banks_SBP(self):
        """Список банков для SBP"""
        return self.__get(action='sbp_list')

    #TODO
    """ Уведомление о выводе
        Для получения уведомлений, укажите в настройках API свой URL для уведомлений
        На данный урл, при изменении статуса, будут отправлены следующие данные"""

    # TODO
    def get_payment_status(self):
        """Получение статуса операции вывода из кошелька"""
        pass

    #TODO
    def transfer(self):
        """Перевод на другой кошелек"""
        pass

    #TODO
    def online_payment(self):
        """Оплата онлайн услуг"""
        pass

    def providers(self):
        """Список сервисов для онлайн оплат"""
        return self.__get(action='providers')

    #TODO
    def check_online_payment(self):
        """Проверка статуса онлайн платежа"""
        pass

    def create_BTC_LTC_ETH_addres(self):
        """Создание BTC/LTC/ETH адреса"""
        return self.__get(action='create_btc_address')

    def get_BTC_LTC_ETH_addres(self):
        """Получение BTC/LTC/ETH адреса"""
        return self.__get(action='get_btc_address')

    #TODO
    def get_info_BTC_LTC_ETH_transaction(self):
        """Получение информации по Bitcoin/Litecoin/Ethereum транзакции"""
        pass

    #TODO
    """ Уведомление о новой Bitcoin/Litecoin/Ethereum транзакции
        Для получения уведомлений, укажите в настройках API свой URL для уведомлений 
        На данный урл, при появлении новой транзакции, будут отправлены следующие данные"""








        # curl -X POST -d 'wallet_id=F112226775&sign=1a189aa7c5aac30d81c67103bc48ddff&action=get_balance' https://fkwallet.com/api_v1.php
        # return self.get_('get_balance')


@dataclass
class FreeKassaClient:
    merchant_id: int
    first_secret: str
    second_secret: str
    freekassa_api_key: str
    wallet_id: str
    fkwallet_api_key: str
    base_url_kassa: str = 'https://api.freekassa.ru/v1/'
    base_url_wallet: str = 'https://fkwallet.com/api_v1.php'
    db: Database = field(init=False, repr=False)
    kassa: FreeKassaApi = field(init=False, repr=False)
    wallet: FKWalletApi = field(init=False, repr=False)

    def __post_init__(self):
        self.db = Database(f'shop{self.merchant_id}.db')
        self.kassa = FreeKassaApi(merchant_id=self.merchant_id, first_secret=self.first_secret,
                                    second_secret=self.second_secret, freekassa_api_key=self.freekassa_api_key,
                                    base_url=self.base_url_kassa, db=self.db)
        self.wallet = FKWalletApi(wallet_id=self.wallet_id, fkwallet_api_key=self.fkwallet_api_key,
                                    base_url=self.base_url_wallet, db=self.db)


client = FreeKassaClient(merchant_id=25089, first_secret='PKio[CmWRxhMUd]', second_secret='(15%Pu%.AK[LfTb',
                         freekassa_api_key='5ce20362620f3092ca3e0035f29c3949', wallet_id='F112226775',
                         fkwallet_api_key='08D69881E1A4F3893AED94146D2B6B27')

# client.wallet.get_balance()
# client.wallet.providers()
client.kassa.get_balance()
