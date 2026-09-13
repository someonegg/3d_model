"""Optional local Bambu Studio slicing audit. Geometry builds do not require Studio."""
from pathlib import Path
import argparse
import hashlib
import json
import sys
import zipfile

HERE=Path(__file__).resolve().parents[1]


sys.path.insert(0, str(HERE.parents[1]))
from tools.slicing import sha, resolve_profiles, run_studio, studio_metadata


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--studio', default='/Applications/BambuStudio.app/Contents/MacOS/BambuStudio')
    parser.add_argument('--profiles', default='/Applications/BambuStudio.app/Contents/Resources/profiles/BBL')
    parser.add_argument('--model-dir',type=Path,default=HERE)
    parser.add_argument('--output-dir',type=Path,default=HERE.parents[1]/'tmp/xc60-slicing')
    parser.add_argument('--only', nargs='*')
    args=parser.parse_args()
    root=args.output_dir.resolve();root.mkdir(parents=True,exist_ok=True)
    source=args.model_dir.resolve()
    resolve=resolve_profiles(Path(args.profiles))
    machine=resolve('Bambu Lab P2S 0.4 nozzle')
    process=resolve('0.16mm Standard @BBL P2S')
    filament=resolve('Bambu PLA Basic @BBL P2S')
    process.update(layer_height='0.16',initial_layer_print_height='0.2',wall_loops='4',
                   sparse_infill_density='15%',enable_support='1',support_type='tree(auto)',
                   support_on_build_plate_only='0',support_threshold_angle='30',
                   support_top_z_distance='0.2',support_object_xy_distance='0.35',
                   brim_type='auto_brim',brim_width='3',outer_wall_speed=['50','50','50'])
    for name,data in [('machine',machine),('process',process),('filament',filament)]:
        (root/f'{name}.json').write_text(json.dumps(data,indent=2)+'\n')
    plates=json.loads((source/'assembly.json').read_text())['plates']
    files=['fit-coupon.stl']+[row['file'] for row in plates]
    if args.only: files=[f for f in files if f in args.only]
    reports=[]
    logs=[]
    for filename in files:
        out=root/Path(filename).stem;out.mkdir(exist_ok=True)
        command=[args.studio,'--datadir',str(root/'config'),
                 '--load-settings',f'{root}/machine.json;{root}/process.json',
                 '--load-filaments',str(root/'filament.json'),
                 '--arrange','0','--orient','0','--slice','0','--export-3mf','sliced.3mf',
                 '--outputdir',str(out),str(source/filename)]
        print('Slicing '+filename,flush=True)
        run_studio(command, out)
        logs.append(out/'studio.log')
        info=json.loads((out/'result.json').read_text())
        if info['return_code'] != 0: raise RuntimeError(info)
        with zipfile.ZipFile(out/'sliced.3mf') as archive:
            config=json.loads(archive.read('Metadata/project_settings.config'))
            assert config['printer_model']=='Bambu Lab P2S'
            assert config['nozzle_diameter']==['0.4']
            assert config['layer_height']=='0.16' and config['wall_loops']=='4'
            assert '256x256' in config['printable_area'], config['printable_area']
            assert float(config['filament_density'][0])>1
            for name in ['Metadata/plate_1.png','Metadata/top_1.png']:
                (out/Path(name).name).write_bytes(archive.read(name))
            gcode=archive.read('Metadata/plate_1.gcode').decode()
            assert '; FEATURE: Outer wall' in gcode or ';TYPE:External perimeter' in gcode
        plates_info=info['sliced_plates']
        assert len(plates_info)==1
        row=plates_info[0]
        reports.append({'file':filename,'sha256':sha(source/filename),'return_code':0,
                        'warning':row.get('warning_message',''),'seconds':row['total_predication'],
                        'filaments':row['filaments'],'features':row['feature_type_times'],
                        'gcode_sha256':hashlib.sha256(gcode.encode()).hexdigest()})
    report={'status':'complete' if len(files)==len(plates)+1 else 'partial',
            'printer':'Bambu Lab P2S','nozzle_mm':.4,'layer_mm':.16,'first_layer_mm':.2,
            'wall_loops':4,'infill_percent':15,'supports':'tree(auto)',
            'profile_sha256':{name:sha(root/f'{name}.json') for name in ['machine','process','filament']},
            'plates':reports,'physical_print_test':False}
    report.update(studio_metadata(args.studio, logs))
    (source/'slicing-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
