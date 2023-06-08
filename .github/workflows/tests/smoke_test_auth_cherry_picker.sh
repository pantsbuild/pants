# Replace our build support files with stub ones
cat << EOF > build-support/bin/cherry_pick/make_pr.sh
#!/usr/bin/env bash
echo "I would've made a PR!"
# We exit 1 to test we still call the finish job
exit 1
EOF
chmod +x build-support/bin/cherry_pick/make_pr.sh

cat << EOF > build-support/bin/cherry_pick/helper.js
class CherryPickHelper {
    constructor({ octokit, context, core }) {}
    async get_prereqs() {
        return {
            pr_num: 12345,
            merge_commit: "ABCDEF12345",
            milestones: ["2.16.x", "2.17.x"],
        };
  }

    async cherry_pick_finished(merge_commit_sha, matrix_info) {
        console.log(\`We finished: \${merge_commit_sha} \${matrix_info}\`);
    }
};

module.exports = CherryPickHelper;
EOF


OUTPUT=$(./act workflow_dispatch -W .github/workflows/auto-cherry-picker.yaml --input PR_number=17295 --env GITHUB_REPOSITORY=pantsbuild/pants)

if [[ ! $OUTPUT =~ "I would've made a PR!" ]]; then
    echo "Did this run the cherry-pick job?"
    exit 1
fi

if [[ ! $OUTPUT =~ 'We finished: ABCDEF12345 [object Object],[object Object]' ]]; then
    echo "Did this run the Post-Pick job?"
    exit 1
fi
