
# Using nodejs-distribution to not clobber the epel node rpm, which we can't use bc it doesn't update regularly enough.
%define   _base nodejs-distribution

# This spec was adapted to be built by Pants. The spec file was adapted from:
#   https://github.com/kazuhisya/nodejs-rpm/blob/master/nodejs.spec

%define   _includedir %{_prefix}/local/include
%define   _bindir %{_prefix}/local/bin
%define   _libdir %{_prefix}/local/lib

Name:          %{_base}
Version:       %{version}
Release:       %{release}%{?dist}
Provides:      %{_base}(engine)
Summary:       Node.js is a server-side JavaScript environment that uses an asynchronous event-driven model.
Group:         Development/Libraries
License:       MIT License
URL:           http://bodega.prod.foursquare.com/4sq-dev/pants/bootstrap/bin
Source0:       node.tar.gz
BuildRoot:     $RPM_BUILD_ROOT
Prefix:        /usr
BuildRequires: tar
BuildRequires: gcc
BuildRequires: gcc-c++
BuildRequires: make
BuildRequires: openssl-devel
BuildRequires: libstdc++-devel
BuildRequires: zlib-devel
BuildRequires: gzip
BuildRequires: python

Patch0: node/node-js.v8_inspector.gyp.patch
Patch1: node/node-js.node.gyp-python27.patch

%description
Node.js is a server-side JavaScript environment that uses an asynchronous event-driven model.
This allows Node.js to get excellent performance based on the architectures of many Internet applications.

%package npm
Summary:       Node Packaged Modules
Group:         Development/Libraries
License:       MIT License
URL:           http://nodejs.org
Obsoletes:     npm
Provides:      npm
Requires:      %{name}

%description npm
Node.js is a server-side JavaScript environment that uses an asynchronous event-driven model.
This allows Node.js to get excellent performance based on the architectures of many Internet applications.

%package devel
Summary:       Header files for %{name}
Group:         Development/Libraries
Requires:      %{name}

%description devel
Node.js is a server-side JavaScript environment that uses an asynchronous event-driven model.
This allows Node.js to get excellent performance based on the architectures of many Internet applications.

%prep
%setup -c -T
%build

%install
rm -rf %{buildroot}
tar zxf $RPM_SOURCE_DIR/node.tar.gz -C $RPM_SOURCE_DIR
mkdir -p %{buildroot}%{_bindir} %{buildroot}%{_libdir} %{buildroot}%{_includedir}
cp -Rp $RPM_SOURCE_DIR/node*/bin/* %{buildroot}%{_bindir}
cp -Rp $RPM_SOURCE_DIR/node*/lib/node_modules %{buildroot}%{_libdir}/node_modules
cp -Rp $RPM_SOURCE_DIR/node*/include/* %{buildroot}%{_includedir}

%files
%defattr(755,root,root)
%{_bindir}/node

%files npm
%defattr(-,produser,foursquare)
%{_libdir}/node_modules/npm
%{_bindir}/npm
%{_bindir}/npx

%files devel
%{_includedir}/node/
