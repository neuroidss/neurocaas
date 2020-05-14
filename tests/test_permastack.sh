#!/bin/bash
set -e
analysisdirname=cianalysispermastack
testgroupid=traviscipermagroup

source "$(dirname $0)"/paths.sh

rootpath=$(dirname $(dirname $(get_abs_filename "$0" )))
cd $rootpath/ncap_iac/ncap_blueprints/


## upload useful resources to the user's area.
python $rootpath/tests/initialize_test_resources.py "$analysisdirname" "$testgroupid"

python $rootpath/tests/initialize_test_submit.py "$analysisdirname" "$testgroupid"
statusbuild=$(bash iac_utils/build.sh $analysisdirname)
statustest=$(bash iac_utils/test_main.sh $analysisdirname)
#newtest=$(bash iac_utils/test_monitor.sh $analysisdirname)

if [ $statustest -eq 0 ]
then
    code=0
else
    echo $statustest
    code=99
fi
echo $code
echo $statustest statustest
echo $statustest >> status.txt
echo $code >> status.txt
echo $statusbuild >> status.txt
exit $code




