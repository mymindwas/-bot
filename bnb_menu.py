from web3 import Web3
import time
import schedule
import logging
from eth_account import Account
import threading

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bnb_menu.log'),
        logging.StreamHandler()
    ]
)

# BNB链配置
BNB_RPC = "https://bsc-dataseed1.binance.org/"
CONTRACT_ADDRESS = Web3.to_checksum_address("0x5B4082965B95a122ca74560868BD085f31B71E0c")
w3 = Web3(Web3.HTTPProvider(BNB_RPC))

# 添加POA中间件以支持BSC链
try:
    from web3.middleware import geth_poa_middleware
    w3.middleware_onion.inject(geth_poa_middleware, layer=0)
except ImportError:
    try:
        from web3.middleware import poa
        w3.middleware_onion.inject(poa, layer=0)
    except ImportError:
        logging.warning("POA middleware not available, continuing without it")

def read_private_keys():
    """读取私钥文件"""
    try:
        with open('bnb_accounts.txt', 'r', encoding='utf-8') as f:
            lines = f.readlines()
            private_keys = [line.strip() for line in lines if line.strip() and not line.startswith('#')]
            return private_keys
    except Exception as e:
        logging.error(f"Error reading private keys: {str(e)}")
        return []

def execute_transaction(private_key, data, value=0, description="transaction"):
    """执行交易"""
    try:
        account = Account.from_key(private_key)
        address = account.address
        
        # 获取nonce并等待确认
        nonce = w3.eth.get_transaction_count(address, 'pending')
        
        # 优化gas设置
        # 使用更高的gas price确保交易被快速处理
        base_gas_price = w3.eth.gas_price
        gas_price = int(base_gas_price * 1)  # 增加20%的gas price
        
        # 根据实际使用情况调整gas limit
        if description == "sign":
            gas_limit = 872541      # 根据你提供的实际使用量1,223,781，设置更高的limit
        else:
            gas_limit = 571060   # 注册交易通常需要更少的gas
        
        transaction = {
            'from': address,
            'to': CONTRACT_ADDRESS,
            'value': value,
            'gas': gas_limit,
            'gasPrice': gas_price,
            'nonce': nonce,
            'data': data,
            'chainId': 56
        }
        
        # 记录gas信息
        gas_price_gwei = w3.from_wei(gas_price, 'gwei')
        logging.info(f"Gas Price: {gas_price_gwei:.2f} Gwei, Gas Limit: {gas_limit:,}")
        
        signed_txn = w3.eth.account.sign_transaction(transaction, private_key)
        
        try:
            tx_hash = w3.eth.send_raw_transaction(signed_txn.rawTransaction)
        except AttributeError:
            tx_hash = w3.eth.send_raw_transaction(signed_txn.raw_transaction)
        
        # 等待交易确认
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
        
        if receipt['status'] == 1:
            gas_used = receipt['gasUsed']
            gas_used_percent = (gas_used / gas_limit) * 100
            logging.info(f"{description.capitalize()} successful for {address}")
            logging.info(f"Gas Used: {gas_used:,} ({gas_used_percent:.1f}%), tx_hash: {tx_hash.hex()}")
            return True
        else:
            logging.error(f"{description.capitalize()} failed for {address}")
            return False
            
    except Exception as e:
        logging.error(f"Error executing {description} for {address}: {str(e)}")
        return False

def register_accounts():
    """注册所有账户"""
    private_keys = read_private_keys()
    logging.info(f"Starting registration for {len(private_keys)} accounts")
    
    for i, private_key in enumerate(private_keys):
        try:
            account = Account.from_key(private_key)
            address = account.address
            balance = w3.eth.get_balance(address)
            balance_bnb = w3.from_wei(balance, 'ether')
            
            logging.info(f"Account {i+1}/{len(private_keys)}: {address}, Balance: {balance_bnb:.6f} BNB")
            
            if balance_bnb < 0.001:
                logging.warning(f"Insufficient balance for {address}, skipping...")
                continue
            
            register_data = "0xf2c298be00000000000000000000000000000000000000000000000000000000000000200000000000000000000000000000000000000000000000000000000000000008345747465a565a30000000000000000000000000000000000000000000000000"
            success = execute_transaction(private_key, register_data, 0, "register")
            time.sleep(3)
            
        except Exception as e:
            logging.error(f"Error processing account {i+1}: {str(e)}")
            continue
    
    logging.info("Registration completed")

def get_recent_claim_amount():
    """获取最近一次Claim Airdrop交易的金额"""
    try:
        import requests
        
        # 使用v2多链API查询BNB链 (chainId: 56)
        API_KEY = "V6BDSCF3SBM5XI9FJHPTS5QVMPG2JX6T28"
        url = "https://api.etherscan.io/v2/api"
        params = {
            'chainid': 56,  # BNB链
            'module': 'account',
            'action': 'txlist',
            'address': CONTRACT_ADDRESS,
            'startblock': 0,
            'endblock': 99999999,
            'page': 1,
            'offset': 20,  # 获取最近100笔交易
            'sort': 'desc',
            'apikey': API_KEY
        }
        
        logging.info("正在使用v2多链API获取BNB链最新Claim交易...")
        response = requests.get(url, params=params, timeout=15)
        data = response.json()
        
        if data.get('status') == '1' and data.get('result'):
            logging.info(f"API返回 {len(data['result'])} 笔交易")
            for tx in data['result']:
                # 查找Claim Airdrop交易 (0x5b88349d)
                if (tx.get('input', '').startswith('0x5b88349d') and 
                    int(tx.get('value', '0')) > 0):
                    
                    amount_wei = int(tx['value'])
                    amount_bnb = w3.from_wei(amount_wei, 'ether')
                    tx_hash = tx.get('hash', 'Unknown')
                    logging.info(f"找到Claim交易: {amount_bnb:.8f} BNB, Hash: {tx_hash}")
                    return amount_wei
            
            logging.warning("在API返回的交易中未找到Claim交易")
        else:
            logging.warning(f"API返回错误: {data.get('message', 'Unknown error')}")
        
        # 如果API失败，使用默认金额
        logging.warning("API方法失败，使用默认金额...")
        return w3.to_wei(0.0004, 'ether')
        
    except Exception as e:
        logging.error(f"Error getting claim amount from API: {str(e)}")
        return w3.to_wei(0.0004, 'ether')



def sign_accounts():
    """签到所有账户"""
    private_keys = read_private_keys()
    logging.info(f"Starting sign for {len(private_keys)} accounts")
    
    # 获取最近的Claim金额
    sign_value = get_recent_claim_amount()
    sign_value_bnb = w3.from_wei(sign_value, 'ether')
    logging.info(f"Using sign amount: {sign_value_bnb:.8f} BNB")
    
    for i, private_key in enumerate(private_keys):
        try:
            account = Account.from_key(private_key)
            address = account.address
            balance = w3.eth.get_balance(address)
            balance_bnb = w3.from_wei(balance, 'ether')
            
            logging.info(f"Account {i+1}/{len(private_keys)}: {address}, Balance: {balance_bnb:.6f} BNB")
            
            if balance_bnb < 0.001:
                logging.warning(f"Insufficient balance for {address}, skipping...")
                continue
            
            sign_data = "0x5b88349d"
            success = execute_transaction(private_key, sign_data, sign_value, "sign")
            time.sleep(3)
            
        except Exception as e:
            logging.error(f"Error processing account {i+1}: {str(e)}")
            continue
    
    logging.info("Sign completed")

def run_scheduler():
    """运行定时任务"""
    while True:
        schedule.run_pending()
        time.sleep(60)

def start_scheduled_sign():
    """启动定时签到"""
    logging.info("Starting scheduled sign")
    
    # 立即执行一次
    sign_accounts()
    
    # 设置定时任务
    schedule.every(730).minutes.do(sign_accounts)  # 12小时10分钟
    
    logging.info("Scheduled sign every 12 hours and 10 minutes")
    
    # 后台运行定时任务
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    
    print("定时签到已启动，按 Ctrl+C 停止...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n定时签到已停止")

def show_menu():
    """显示菜单"""
    print("\n" + "="*50)
    print("BNB链自动签到脚本")
    print("="*50)
    print("1. 执行注册")
    print("2. 执行一次签到")
    print("3. 启动定时签到 (每隔12小时10分钟)")
    print("4. 退出")
    print("="*50)

def main():
    logging.info("Starting BNB menu script")
    
    while True:
        show_menu()
        choice = input("请选择操作 (1-4): ").strip()
        
        if choice == '1':
            print("开始执行注册...")
            register_accounts()
            print("注册完成！")
            
        elif choice == '2':
            print("开始执行签到...")
            sign_accounts()
            print("签到完成！")
            
        elif choice == '3':
            print("启动定时签到...")
            start_scheduled_sign()
            
        elif choice == '4':
            print("退出程序...")
            break
            
        else:
            print("无效选择，请重新输入！")
        
        if choice in ['1', '2']:
            input("按回车键继续...")

if __name__ == "__main__":
    main()
