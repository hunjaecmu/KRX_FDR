# scripts/update_data.py

from data_store import run_all

if __name__ == "__main__":
    print("데이터 업데이트 시작")
    run_all(
        force_master_update=False,
        derive_all=True
    )
    print("데이터 업데이트 완료")