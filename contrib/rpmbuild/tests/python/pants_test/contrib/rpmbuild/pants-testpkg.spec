Summary: A test package
Name: pants-testpkg
Version: %{version}
Release: 1
BuildArch: noarch
License: Apache

Source0: do-nothing.sh

%description
A simple RPM package for testing the Pants rpmbuild plugin

%prep
%setup -c -T

%build

%install
mkdir -p "${RPM_BUILD_ROOT}/usr/local/bin"
cp "${RPM_SOURCE_DIR}/do-nothing.sh" "${RPM_BUILD_ROOT}/usr/local/bin"

%files
/usr/local/bin/do-nothing.sh
