
py -m venv .venv     ------> windows
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process



.venv\Scripts\activate

source .venv/bin/activate   ---------->  ubuntu
python.exe -m pip install --upgrade pip
pip install -r requirements.txt

python -m numde.downloader


python -m numde


python working_detector.py




pyinstaller --onefile --windowed --add-data "models/trocr-large-printed;models/trocr-large-printed" --add-data "best.pt;." -n "AWND_DUO" aw_6\__main__.py

pyinstaller --onefile --add-data "models/trocr-large-printed;models/trocr-large-printed" --add-data "best.pt;." -n "AWND_DUO" aw_6\__main__.py

pyinstaller --onefile --add-data "models/trocr-small-printed:models/trocr-small-printed" --add-data "best.pt:." 
  -n AWND_DUO aw_6/__main__.py  ---->უბუნტუ



